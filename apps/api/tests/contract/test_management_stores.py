from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest

from ahq.adapters.memory_management import (
    MemoryControlStore,
    MemoryEvalStore,
    MemoryQualityStore,
    MemoryRunLedger,
    MemorySlots,
    MemoryVersionStore,
)
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgControlStore, PgEvalStore, PgQualityStore, PgRunLedger, PgSlots, PgVersionStore
from ahq.domain import (
    AgentControl,
    AgentRun,
    AgentVersion,
    ConflictError,
    CriterionVerdict,
    EvalCase,
    EvalRun,
    GateParams,
    GateSummary,
    QALabel,
    ReviewRecord,
    VersionConfig,
    VersionScore,
    VersionStatus,
    version_id_for,
)
from ahq.ports import ControlStore, EvalStore, QualityStore, RunLedger, Slots, VersionStore

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
TABLES = (
    "agents.eval_cases, agents.eval_runs, agents.qa_labels, agents.qa_reviews, agents.model_health, "
    "agents.spend_daily, agents.agent_controls, agents.agent_runs, agents.agent_versions, agents.provider_slots"
)


@dataclass
class Stores:
    versions: VersionStore
    runs: RunLedger
    controls: ControlStore
    quality: QualityStore
    evals: EvalStore
    slots: Slots


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
async def stores(request: pytest.FixtureRequest) -> AsyncIterator[Stores]:
    if request.param == "memory":
        yield Stores(
            MemoryVersionStore(),
            MemoryRunLedger(),
            MemoryControlStore(),
            MemoryQualityStore(),
            MemoryEvalStore(),
            MemorySlots(),
        )
        return
    url: str = request.getfixturevalue("pg_url")
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {TABLES}")
    engine = make_engine(url)
    sessions = make_sessionmaker(engine)
    yield Stores(
        PgVersionStore(sessions),
        PgRunLedger(sessions),
        PgControlStore(sessions),
        PgQualityStore(sessions),
        PgEvalStore(sessions),
        PgSlots(sessions),
    )
    await engine.dispose()


def version(
    number: int, *, status: VersionStatus = VersionStatus.DRAFT, prompt: str = "", agent: str = "support"
) -> AgentVersion:
    config = VersionConfig(
        prompt_stable=f"You help customers. {prompt}",
        prompt_context="## Context\n\nToday is {today}.",
        tools=["knowledge_search"],
        max_model_calls=10,
        max_usd=0.5,
    )
    return AgentVersion(
        version_id=version_id_for(agent, number),
        agent=agent,
        number=number,
        status=status,
        config=config,
        digest=config.digest,
        note="",
        created_by="code",
        created_at=NOW + timedelta(minutes=number),
        status_at=NOW,
    )


def run(work_item_id: str, *, outcome: str = "resolved", version_id: str = "support@1", minute: int = 0) -> AgentRun:
    return AgentRun(
        work_item_id=work_item_id,
        agent="support",
        version_id=version_id,
        kind="ticket",
        outcome=outcome,  # pyright: ignore[reportArgumentType]
        turns=1,
        model_calls=3,
        tool_calls=2,
        input_tokens=900,
        output_tokens=100,
        cost_usd=0.01,
        seconds=4.2,
        started_at=NOW,
        updated_at=NOW + timedelta(minutes=minute),
    )


async def test_a_version_with_the_same_content_is_stored_once(stores: Stores) -> None:
    first = await stores.versions.create(version(1, status=VersionStatus.LIVE))
    again = await stores.versions.create(version(2, status=VersionStatus.DRAFT))

    assert again == first
    assert await stores.versions.next_number("support") == 2


async def test_one_live_version_and_one_canary_per_agent(stores: Stores) -> None:
    await stores.versions.create(version(1, status=VersionStatus.LIVE))
    await stores.versions.create(version(2, prompt="Be brief."))
    await stores.versions.create(version(3, prompt="Be warm."))

    canary = await stores.versions.set_status(
        "support@2", VersionStatus.CANARY, expected={VersionStatus.DRAFT}, at=NOW, canary_pct=20
    )
    with pytest.raises(ConflictError):
        await stores.versions.set_status("support@3", VersionStatus.CANARY, expected={VersionStatus.DRAFT}, at=NOW)
    with pytest.raises(ConflictError):
        await stores.versions.set_status("support@2", VersionStatus.CANARY, expected={VersionStatus.DRAFT}, at=NOW)

    serving = await stores.versions.serving("support")
    assert (serving.live and serving.live.version_id, serving.canary) == ("support@1", canary)
    assert canary.canary_pct == 20


async def test_promoting_retires_the_live_version(stores: Stores) -> None:
    await stores.versions.create(version(1, status=VersionStatus.LIVE))
    await stores.versions.create(version(2, prompt="Be brief.", status=VersionStatus.CANARY))

    live, retired = await stores.versions.promote(
        "support@2", expected={VersionStatus.CANARY}, at=NOW, reason="clean canary"
    )

    assert (live.status, live.status_reason) == (VersionStatus.LIVE, "clean canary")
    assert retired is not None
    assert (retired.version_id, retired.status) == ("support@1", VersionStatus.RETIRED)
    assert [v.version_id for v in await stores.versions.list("support")] == ["support@2", "support@1"]
    with pytest.raises(ConflictError):
        await stores.versions.promote("support@2", expected={VersionStatus.CANARY}, at=NOW, reason="again")


async def test_eval_summaries_attach_to_versions(stores: Stores) -> None:
    await stores.versions.create(version(1))

    updated = await stores.versions.set_eval_summary("support@1", {"passed": True, "score": 0.8})

    assert updated.eval_summary == {"passed": True, "score": 0.8}
    assert (await stores.versions.get("support@1")) == updated


async def test_runs_are_replaced_with_their_latest_totals(stores: Stores) -> None:
    await stores.runs.record([run("wi_1", outcome="waiting_customer")])
    await stores.runs.record([run("wi_1", outcome="resolved", minute=5), run("wi_2", version_id="support@2", minute=1)])

    assert (await stores.runs.get("wi_1", "support")) == run("wi_1", outcome="resolved", minute=5)
    assert [r.work_item_id for r in await stores.runs.runs(agent="support")] == ["wi_1", "wi_2"]
    assert [r.work_item_id for r in await stores.runs.runs(version_id="support@2")] == ["wi_2"]
    assert [r.work_item_id for r in await stores.runs.runs(since=NOW + timedelta(minutes=2))] == ["wi_1"]


async def test_only_finished_runs_when_asked(stores: Stores) -> None:
    await stores.runs.record([run("wi_1", outcome="waiting_customer"), run("wi_2", outcome="escalated")])

    assert [r.work_item_id for r in await stores.runs.runs(finished=True)] == ["wi_2"]
    assert [r.work_item_id for r in await stores.runs.runs(finished=False)] == ["wi_1"]


async def test_pause_switches_are_kept_per_agent(stores: Stores) -> None:
    await stores.controls.set_control(
        AgentControl(agent="support", paused=True, reason="bad replies", changed_by="operator", changed_at=NOW)
    )
    resumed = AgentControl(agent="support", paused=False, changed_by="operator", changed_at=NOW)
    await stores.controls.set_control(resumed)

    assert await stores.controls.controls() == {"support": resumed}


async def test_spend_adds_up_per_day_agent_and_model(stores: Stores) -> None:
    day = date(2026, 6, 15)
    await stores.controls.add_spend(day, "support", "gpt-6-luna", cost_usd=0.01, ok=True)
    await stores.controls.add_spend(day, "support", "gpt-6-luna", cost_usd=0.02, ok=False)
    await stores.controls.add_spend(day + timedelta(days=1), "support", "gpt-6-luna", cost_usd=1.0, ok=True)

    [line] = await stores.controls.spend(day)
    assert (line.calls, line.errors, round(line.cost_usd, 6)) == (2, 1, 0.03)


async def test_the_breaker_opens_on_the_third_error_in_a_row_and_a_success_heals_it(stores: Stores) -> None:
    cooldown = timedelta(minutes=10)

    async def call(ok: bool, at: datetime = NOW) -> bool:
        _, opened = await stores.controls.record_call(
            "gpt-6-luna", ok=ok, at=at, errors_to_open=3, cooldown=cooldown, error=None if ok else "timeout"
        )
        return opened

    assert [await call(False), await call(True), await call(False), await call(False), await call(False)] == [
        False,
        False,
        False,
        False,
        True,
    ]
    health = (await stores.controls.health())["gpt-6-luna"]
    assert health.is_open(NOW + timedelta(minutes=9))
    assert not health.is_open(NOW + timedelta(minutes=11))
    assert not await call(False)
    assert await call(False, NOW + timedelta(minutes=11))
    await call(True, NOW + timedelta(minutes=30))
    healed = (await stores.controls.health())["gpt-6-luna"]
    assert (healed.consecutive_errors, healed.open_until) == (0, None)


def review(work_item_id: str, *, minute: int = 0) -> ReviewRecord:
    return ReviewRecord(
        review_id=f"qa_{work_item_id}_support",
        work_item_id=work_item_id,
        agent="support",
        version_id="support@1",
        rubric="support@1",
        judge_model="gpt-6-luna",
        reason="sample",
        criteria=[CriterionVerdict(criterion_id="tone", critique="Polite throughout.", verdict="pass")],
        summary="Fine.",
        cost_usd=0.001,
        created_at=NOW + timedelta(minutes=minute),
    )


async def test_one_review_per_run(stores: Stores) -> None:
    first = await stores.quality.save_review(review("wi_1"))
    again = await stores.quality.save_review(review("wi_1", minute=3))

    assert again == first
    assert await stores.quality.review("wi_1", "support") == first


async def test_labeled_reviews_leave_the_queue_and_relabeling_replaces(stores: Stores) -> None:
    for index, work_item_id in enumerate(("wi_1", "wi_2", "wi_3")):
        await stores.quality.save_review(review(work_item_id, minute=index))
    label = QALabel(
        work_item_id="wi_2", agent="support", criterion_id="tone", verdict="fail", labeled_by="admin", labeled_at=NOW
    )
    await stores.quality.save_labels([label])
    await stores.quality.save_labels([label.model_copy(update={"verdict": "pass"})])

    assert [r.work_item_id for r in await stores.quality.unlabeled()] == ["wi_3", "wi_1"]
    assert [(lab.work_item_id, lab.verdict) for lab in await stores.quality.labels()] == [("wi_2", "pass")]
    assert [r.work_item_id for r in await stores.quality.reviews(since=NOW + timedelta(minutes=1))] == ["wi_3", "wi_2"]


def eval_run(eval_run_id: str = "ev_1") -> EvalRun:
    return EvalRun(
        eval_run_id=eval_run_id,
        agent="support",
        candidate_id="support@2",
        baseline_id="support@1",
        params=GateParams(suite="tau3"),
        status="queued",
        backend="inprocess",
        requested_by="operator",
        created_at=NOW,
    )


async def test_eval_runs_move_from_queued_to_a_verdict(stores: Stores) -> None:
    await stores.evals.create(eval_run())
    with pytest.raises(ConflictError):
        await stores.evals.create(eval_run())
    running = await stores.evals.update("ev_1", status="running", at=NOW, url="https://example.test/run/1")
    summary = GateSummary(
        candidate=VersionScore(version_id="support@2", metric="pass^1", score=1.0, cases=2, passed=2, cost_usd=0.02),
        baseline=VersionScore(version_id="support@1", metric="pass^1", score=0.5, cases=2, passed=1, cost_usd=0.02),
        passed=True,
        reasons=[],
    )
    done = await stores.evals.update("ev_1", status="passed", at=NOW + timedelta(minutes=5), summary=summary)

    assert (running.started_at, running.url) == (NOW, "https://example.test/run/1")
    assert (done.started_at, done.finished_at, done.summary) == (NOW, NOW + timedelta(minutes=5), summary)
    assert [r.eval_run_id for r in await stores.evals.list(agent="support")] == ["ev_1"]


async def test_eval_cases_are_replaced_per_version_case_and_trial(stores: Stores) -> None:
    await stores.evals.create(eval_run())
    case = EvalCase(version_id="support@2", case_id="7", trial=0, passed=False, score=0.0, cost_usd=0.01, seconds=3)
    await stores.evals.add_cases("ev_1", [case, case.model_copy(update={"version_id": "support@1"})])
    await stores.evals.add_cases("ev_1", [case.model_copy(update={"passed": True, "score": 1.0})])

    cases = await stores.evals.cases("ev_1")
    assert [(c.version_id, c.passed) for c in cases] == [("support@1", False), ("support@2", True)]


async def test_a_provider_has_only_its_slots_and_a_released_or_expired_one_is_free(stores: Stores) -> None:
    until = NOW + timedelta(minutes=1)
    taken = [await stores.slots.acquire("openai", f"h{n}", limit=2, now=NOW, until=until) for n in range(3)]
    assert taken == [True, True, False]
    assert await stores.slots.acquire("anthropic", "h9", limit=2, now=NOW, until=until)
    await stores.slots.release("openai", "h0")
    assert await stores.slots.acquire("openai", "h3", limit=2, now=NOW, until=until)
    assert not await stores.slots.acquire("openai", "h4", limit=2, now=NOW, until=until)
    later = until + timedelta(seconds=1)
    assert await stores.slots.acquire("openai", "h5", limit=2, now=later, until=later + timedelta(minutes=1))


async def test_concurrent_callers_never_share_a_slot(stores: Stores) -> None:
    until = NOW + timedelta(minutes=1)
    taken = await asyncio.gather(
        *(stores.slots.acquire("openai", f"h{n}", limit=3, now=NOW, until=until) for n in range(12))
    )
    assert sum(taken) == 3

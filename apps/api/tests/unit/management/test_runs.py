from __future__ import annotations

import pytest

from ahq.adapters.memory_management import MemoryEvalStore
from ahq.agents import SUPPORT, version_config
from ahq.config import load_canary_config, load_qa_config
from ahq.domain import ConfigurationError, EvalRun, QaReviewJob, VersionStatus
from ahq.management import EvalDesk, review_reason
from tests.unit.management.helpers import Desk, agent_run

QA = load_qa_config()


def test_runs_are_picked_for_review_by_what_happened() -> None:
    assert review_reason(agent_run("wi_1", outcome="escalated"), canary=False, config=QA) == "escalation"
    assert review_reason(agent_run("wi_1", rejected=1), canary=False, config=QA) == "rejected_approval"
    assert review_reason(agent_run("wi_1"), canary=True, config=QA) == "canary"
    assert review_reason(agent_run("wi_1", outcome="failed"), canary=True, config=QA) is None
    assert review_reason(agent_run("wi_1", outcome="waiting_customer"), canary=True, config=QA) is None
    sampled = [review_reason(agent_run(f"wi_{n}"), canary=False, config=QA) for n in range(1_000)]
    assert sampled.count(None) + sampled.count("sample") == 1_000
    assert 150 < sampled.count("sample") < 250


async def test_finished_runs_are_recorded_and_reviewed() -> None:
    desk = Desk()
    await desk.registry.sync()
    await desk.runs.after_run([agent_run("wi_1", outcome="escalated"), agent_run("wi_2", outcome="waiting_customer")])

    assert await desk.ledger.get("wi_2", "support") is not None
    assert [(job.work_item_id, job.reason) for job in desk.queue.jobs if isinstance(job, QaReviewJob)] == [
        ("wi_1", "escalation")
    ]


async def test_a_canary_that_escalates_everything_is_rolled_back() -> None:
    desk = Desk()
    await desk.registry.sync()
    await desk.runs.after_run([agent_run(f"wi_live_{n}") for n in range(10)])
    config = version_config(SUPPORT).model_copy(update={"max_usd": 0.2})
    draft = await desk.registry.draft("support", config, note="Cheaper.", by="op")
    await desk.registry.start_canary(draft.version_id, pct=50, by="op", skip_gate=True)

    for n in range(6):
        await desk.runs.after_run([agent_run(f"wi_{n}", draft.version_id, "escalated")])

    version = await desk.registry.get(draft.version_id)
    assert version.status is VersionStatus.RETIRED
    assert version.status_reason == "rolled back: escalation rate 100% on the canary against 0% live"
    reviewed = [job for job in desk.queue.jobs if isinstance(job, QaReviewJob) and job.version_id == draft.version_id]
    assert [job.reason for job in reviewed] == ["canary"] * 6


async def test_an_agent_whose_runs_keep_failing_is_paused() -> None:
    desk = Desk()
    for n in range(5):
        await desk.runs.after_failure([agent_run(f"wi_{n}", outcome="failed")])
    assert await desk.limiter.paused() == {"support"}
    assert (await desk.kinds()).count("agent.paused") == 1


async def test_a_deployment_without_a_gate_backend_refuses_before_creating_a_run() -> None:
    desk = Desk()
    await desk.registry.sync()
    evals = EvalDesk(
        MemoryEvalStore(),
        desk.registry,
        None,
        desk.events,
        desk.clock,
        load_canary_config(),
        backend="inprocess",
        profile=lambda: "mock",
    )
    config = version_config(SUPPORT).model_copy(update={"max_model_calls": 9})
    draft = await desk.registry.draft("support", config, note="Fewer calls.", by="op")
    with pytest.raises(ConfigurationError):
        await evals.request(draft.version_id, by="op")
    assert await evals.store.list() == []


async def test_a_refused_dispatch_marks_the_run_as_an_error() -> None:
    class Refusing:
        async def launch(self, run: EvalRun) -> None:
            raise ConfigurationError("GitHub did not start the eval workflow")

    desk = Desk()
    await desk.registry.sync()
    evals = EvalDesk(
        MemoryEvalStore(),
        desk.registry,
        Refusing(),
        desk.events,
        desk.clock,
        load_canary_config(),
        backend="github",
        profile=lambda: "low",
    )
    config = version_config(SUPPORT).model_copy(update={"max_model_calls": 9})
    draft = await desk.registry.draft("support", config, note="Fewer calls.", by="op")
    with pytest.raises(ConfigurationError):
        await evals.request(draft.version_id, by="op")
    [run] = await evals.store.list()
    assert (run.status, run.error, run.params.profile) == ("error", "GitHub did not start the eval workflow", "low")

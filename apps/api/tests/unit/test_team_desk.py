from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from pydantic import JsonValue

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import (
    MemoryApprovalStore,
    MemoryEventLog,
    MemorySimStore,
    MemoryTeamRecords,
    MemoryWorkStore,
    MemoryWorldRepo,
)
from ahq.adapters.queue_inprocess import InProcessQueue
from ahq.config import load_retrieval_config
from ahq.domain import (
    ConflictError,
    EventKind,
    KbDraft,
    KpiAlert,
    PatternFlag,
    Proposal,
    ProposalRecord,
    WorkItemId,
    WorkKind,
)
from ahq.domain.sim import SimRun
from ahq.retrieval import KB_PENDING, HybridRetriever, KbDocument, KnowledgeBase, SearchRequest, ingest, load_documents
from ahq.runtime import Commands, StoreTime, TeamDesk
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse, OverlapReranker
from ahq.testing.qdrant import LocalVectorStore

NOW = datetime(2026, 6, 15, 15, 0, tzinfo=UTC)
TODAY = date(2026, 6, 15)
ALERT = KpiAlert(
    metric="late_or_overdue_rate",
    segment={"carrier": "northstar", "region": "midwest"},
    window_hours=3,
    value=0.5,
    baseline=0.1,
    z_score=8.0,
    ratio=5.0,
    samples=30,
    detected_at=NOW,
)
FLAG = PatternFlag(topic="delivery", summary="Northstar parcels to Ohio are days late.", ticket_ids=["tk_1"])
NOTICE = KbDocument(
    doc_id="help-midwest-delays",
    title="Delays in the Midwest",
    namespace="shipping",
    audience="customer",
    version=1,
    effective_date=TODAY,
    source="draft:drf_1",
    body="# Delays in the Midwest\n\nQuokka parcels are late.\n\n## What to expect\n\nOne to three extra quokka days.",
)


@dataclass
class Desk:
    desk: TeamDesk
    work: MemoryWorkStore
    queue: InProcessQueue
    events: MemoryEventLog
    records: MemoryTeamRecords
    store: LocalVectorStore
    retriever: HybridRetriever


@pytest.fixture
async def desk() -> AsyncIterator[Desk]:
    clock = ManualClock(NOW)
    work, events, queue, records = MemoryWorkStore(clock), MemoryEventLog(), InProcessQueue(), MemoryTeamRecords()
    store, embedder, sparse = LocalVectorStore(), HashEmbedder(), HashingSparse()
    await ingest(store, embedder, sparse, load_documents(REPO_ROOT / "kb"))
    commands = Commands(
        work=work,
        approvals=MemoryApprovalStore(clock),
        events=events,
        queue=queue,
        clock=clock,
        tickets=MemoryWorldRepo(),
    )
    knowledge = KnowledgeBase(store, embedder, sparse)
    team = TeamDesk(commands=commands, records=records, knowledge=knowledge, events=events, clock=clock)
    retriever = HybridRetriever(store, embedder, OverlapReranker(), sparse, load_retrieval_config())
    yield Desk(team, work, queue, events, records, store, retriever)
    await store.close()


async def kinds(desk: Desk) -> list[EventKind]:
    return [event.kind for event in await desk.events.read_after(0, limit=100)]


async def with_draft(desk: Desk) -> str:
    await desk.records.save_draft(
        KbDraft(
            draft_id="drf_1",
            doc_id=NOTICE.doc_id,
            version=1,
            document=NOTICE.model_dump(mode="json"),
            status="pending",
            created_at=NOW,
        )
    )
    await desk.desk.knowledge.stage(NOTICE)
    proposal = Proposal(
        kind="kb_article",
        title="Publish a delay notice",
        problem="Customers do not know why parcels are late.",
        evidence=["tk_1"],
        proposal="Publish the notice.",
        expected_impact="Fewer tickets.",
        risk="Low.",
        draft_id="drf_1",
    )
    record = ProposalRecord(
        proposal_id="prp_1_0",
        work_item_id="wi_1",
        incident_id=None,
        proposal=proposal,
        status="pending",
        created_at=NOW,
    )
    await desk.records.add_proposals([record])
    return record.proposal_id


async def notice_is_searchable(desk: Desk) -> bool:
    request = SearchRequest(query="quokka parcels late", as_of=TODAY, namespaces=("shipping",), k=10)
    passages = (await desk.retriever.search(request)).passages
    return any(passage.doc_id == NOTICE.doc_id for passage in passages)


async def test_an_alert_raised_twice_the_same_day_becomes_work_once(desk: Desk) -> None:
    first = await desk.desk.raise_alert(ALERT, TODAY)
    second = await desk.desk.raise_alert(ALERT, TODAY)
    assert first.id == second.id
    assert first.kind is WorkKind.ALERT
    assert (await kinds(desk)).count(EventKind.WORK_CREATED) == 1
    assert desk.queue.pending == 1


async def ticket_work(desk: Desk, sim_run: str | None = None) -> str:
    work_input: dict[str, JsonValue] = {"ticket_id": "tk_1", "today": TODAY.isoformat()}
    if sim_run is not None:
        work_input["sim_run"] = sim_run
    return (await desk.work.create(WorkKind.TICKET, work_input)).id


async def test_flags_on_one_topic_share_the_work_that_looks_into_them(desk: Desk) -> None:
    a, b, c = [await ticket_work(desk) for _ in range(3)]
    first = await desk.desk.raise_flag(a, FLAG, TODAY)
    second = await desk.desk.raise_flag(b, FLAG.model_copy(update={"ticket_ids": ["tk_2"]}), TODAY)
    other = await desk.desk.raise_flag(c, FLAG.model_copy(update={"topic": "product"}), TODAY)
    assert first == second != other
    assert (await kinds(desk)).count(EventKind.PATTERN_FLAGGED) == 3
    item = await desk.work.by_key(f"flag:live:delivery:{TODAY}")
    assert item is not None
    assert item.input["source"] == a


async def test_each_simulator_run_gets_its_own_alerts_and_flags(desk: Desk) -> None:
    assert (await desk.desk.raise_alert(ALERT, TODAY, scope="sim_1")).id != (
        await desk.desk.raise_alert(ALERT, TODAY, scope="sim_2")
    ).id
    first = await desk.desk.raise_flag(await ticket_work(desk, "sim_1"), FLAG, TODAY)
    second = await desk.desk.raise_flag(await ticket_work(desk, "sim_2"), FLAG, TODAY)
    assert first != second


async def test_flags_can_be_noted_without_starting_work(desk: Desk) -> None:
    quiet = TeamDesk(
        commands=desk.desk.commands,
        records=desk.records,
        knowledge=desk.desk.knowledge,
        events=desk.events,
        clock=desk.desk.clock,
        start_flagged_work=False,
    )
    assert await quiet.raise_flag(await ticket_work(desk), FLAG, TODAY) is None
    assert await desk.work.by_key(f"flag:live:delivery:{TODAY}") is None
    assert EventKind.PATTERN_FLAGGED in await kinds(desk)


async def test_a_flag_raised_during_a_simulated_day_carries_the_days_time(desk: Desk) -> None:
    store_hour = datetime(2026, 6, 16, 0, 35, tzinfo=UTC)
    runs = MemorySimStore(desk.desk.clock)
    await runs.create(
        SimRun(
            run_id="sim_1",
            scenario="showcase",
            seed=7,
            status="running",
            started_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
            ends_at=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
            sim_now=store_hour,
            tick_no=150,
            tick_minutes=5,
            tick_seconds=6.25,
            created_at=NOW,
            updated_at=NOW,
        ),
        [],
    )
    team = TeamDesk(
        commands=desk.desk.commands,
        records=desk.records,
        knowledge=desk.desk.knowledge,
        events=desk.events,
        clock=desk.desk.clock,
        store_time=StoreTime(work=desk.work, runs=runs, clock=desk.desk.clock),
    )
    simulated = await team.raise_flag(await ticket_work(desk, "sim_1"), FLAG, TODAY)
    live = await team.raise_flag(await ticket_work(desk), FLAG, TODAY)
    assert simulated is not None
    assert live is not None
    assert (await desk.work.get(WorkItemId(simulated))).input["raised_at"] == store_hour.isoformat()
    assert (await desk.work.get(WorkItemId(live))).input["raised_at"] == NOW.isoformat()


async def test_approving_a_proposal_publishes_its_draft(desk: Desk) -> None:
    proposal_id = await with_draft(desk)
    assert not await notice_is_searchable(desk)
    decided = await desk.desk.decide_proposal(proposal_id, "approved", actor="operator", note="Good.")
    assert decided.status == "approved"
    assert await notice_is_searchable(desk)
    assert await desk.store.count(KB_PENDING) == 0
    draft = await desk.records.draft("drf_1")
    assert draft is not None
    assert draft.status == "published"
    assert {EventKind.KB_PUBLISHED, EventKind.PROPOSAL_DECIDED} <= set(await kinds(desk))
    with pytest.raises(ConflictError):
        await desk.desk.decide_proposal(proposal_id, "rejected", actor="operator")


async def test_rejecting_a_proposal_discards_its_draft(desk: Desk) -> None:
    proposal_id = await with_draft(desk)
    await desk.desk.decide_proposal(proposal_id, "rejected", actor="operator", note="Not now.")
    assert not await notice_is_searchable(desk)
    assert await desk.store.count(KB_PENDING) == 0
    draft = await desk.records.draft("drf_1")
    assert draft is not None
    assert draft.status == "rejected"
    assert EventKind.KB_PUBLISHED not in await kinds(desk)

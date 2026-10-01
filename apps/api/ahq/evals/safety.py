from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from datetime import datetime

from pydantic import Field, JsonValue

from ahq.adapters.clock import WallClock
from ahq.adapters.embedding_cache import CachingEmbedder
from ahq.agents import SUPPORT
from ahq.app.container import Container, Overrides, open_container, open_embedder
from ahq.config import ProfileName, load_model_catalog, load_world_config
from ahq.domain import ApprovalDecision, CustomerTurnJob, Event, EventKind, StrictModel, WorkItemId, WorkStatus
from ahq.domain.retail import RetailSnapshot
from ahq.domain.world import TicketMessage
from ahq.grading import SafetyCase, SafetySummary, SafetyVerdict, Trace, grade_safety, summarize
from ahq.retrieval import KbDocument
from ahq.settings import REPO_ROOT, Settings
from ahq.sim.customer import GREETING, scenario
from ahq.tools import ANOTHER_CUSTOMER, AUTHENTICATE_FIRST

DATASET = REPO_ROOT / "evals" / "datasets" / "safety_attacks.jsonl"
SUBJECT = "Customer chat"
REFUSALS = (ANOTHER_CUSTOMER, AUTHENTICATE_FIRST, "is not available to", "Refused:")
POLICY_MARKER = "<policy>"


class SafetyResult(StrictModel):
    verdict: SafetyVerdict
    outcome: str
    cost_usd: float
    seconds: float
    error: str | None = None
    transcript: list[str] = Field(default_factory=list)


class SafetyReport(StrictModel):
    profile: ProfileName
    screen: bool
    started_at: datetime
    results: list[SafetyResult]
    summary: SafetySummary
    cost_usd: float
    stopped_at_cap: bool


async def run_safety(
    settings: Settings,
    cases: Sequence[SafetyCase],
    store: RetailSnapshot,
    *,
    screen: bool,
    max_usd: float,
    concurrency: int = 1,
    progress: Callable[[SafetyResult], None] | None = None,
) -> SafetyReport:
    started = WallClock().now()
    run_settings = settings.model_copy(
        update={"queue_backend": "inprocess", "tool_transport": "direct", "qdrant_url": None, "database_url": None}
    )
    results: list[SafetyResult] = []
    spent = 0.0
    capped = False
    gate = asyncio.Semaphore(concurrency)
    async with AsyncExitStack() as stack:
        embedder = await stack.enter_async_context(open_embedder(run_settings, load_model_catalog()))
        if run_settings.model_profile != "mock":
            cache = CachingEmbedder(
                embedder,
                run_settings.data_dir / "cache" / "embeddings.sqlite",
                model=load_model_catalog().embeddings.id,
            )
            stack.callback(cache.close)
            embedder = cache

        async def attempt(case: SafetyCase) -> None:
            nonlocal spent, capped
            async with gate:
                if spent >= max_usd:
                    capped = True
                    return
                overrides = Overrides(
                    storage="memory",
                    store=store,
                    embedder=embedder,
                    flags_start_work=False,
                    review_runs=False,
                    input_check=screen,
                )
                result = await run_case(run_settings, overrides, case)
                spent += result.cost_usd
                results.append(result)
                if progress is not None:
                    progress(result)

        await asyncio.gather(*(attempt(case) for case in cases))
    order = {case.case_id: n for n, case in enumerate(cases)}
    results.sort(key=lambda r: order[r.verdict.case_id])
    return SafetyReport(
        profile=run_settings.model_profile,
        screen=screen,
        started_at=started,
        results=results,
        summary=summarize(r.verdict for r in results),
        cost_usd=round(spent, 6),
        stopped_at_cap=capped,
    )


async def run_case(settings: Settings, overrides: Overrides, case: SafetyCase) -> SafetyResult:
    clock = WallClock()
    began = clock.now()
    async with open_container(settings, overrides=overrides) as container:
        today = load_world_config().anchor.date()
        if case.draft is not None:
            draft = KbDocument(
                doc_id=case.draft.doc_id,
                title=case.draft.title,
                namespace=case.draft.namespace,
                audience="customer",
                version=1,
                effective_date=today,
                source="draft",
                body=case.draft.body,
            )
            await container.knowledge.stage(draft)
        before = await container.retail.snapshot()
        error = None
        item_id: WorkItemId | None = None
        try:
            item_id = await _converse(container, case)
            outcome = _outcome((await container.work.get(item_id)).status)
        except Exception as failure:  # a failed case is a result, not the end of the run
            outcome, error = "error", f"{type(failure).__name__}: {failure}"
        ticket = await container.tickets.ticket(_ticket_id(case))
        messages: list[TicketMessage] = list(ticket.messages) if ticket is not None else []
        events = await container.events.read_after(0, limit=100_000)
        mine = [e for e in events if item_id is not None and e.work_item_id == item_id]
        verdict = grade_safety(
            case,
            before,
            await container.retail.snapshot(),
            customer_wrote="\n".join(m.body for m in messages if m.author == "customer"),
            replies=[m.body for m in messages[1:] if m.author == "agent"],
            citations=_citations(mine),
            instructions=SUPPORT.prompt.stable.split(POLICY_MARKER, 1)[0],
            trace=trace_of(mine),
        )
        cost = sum(
            float(e.payload.get("cost_usd") or 0.0)  # pyright: ignore[reportArgumentType]
            for e in events
            if e.kind is EventKind.MODEL_CALLED
        )
    return SafetyResult(
        verdict=verdict,
        outcome=outcome,
        cost_usd=round(cost, 6),
        seconds=round((clock.now() - began).total_seconds(), 1),
        error=error,
        transcript=[f"{m.author}: {m.body}" for m in messages],
    )


def trace_of(events: Sequence[Event]) -> Trace:
    blocked = [e for e in events if e.kind is EventKind.GUARDRAIL_BLOCKED]
    return Trace(
        screen_blocked=any(e.payload.get("stage") == "input" for e in blocked),
        routed_to_person=any(e.kind is EventKind.WORK_ROUTED and e.payload.get("route") == "human" for e in events),
        tool_refusals=sum(
            e.kind is EventKind.TOOL_CALLED and any(r in str(e.payload.get("error") or "") for r in REFUSALS)
            for e in events
        ),
        approvals=sum(e.kind is EventKind.APPROVAL_REQUESTED for e in events),
        reply_blocked=any(e.payload.get("stage") == "output" for e in blocked),
    )


async def _converse(container: Container, case: SafetyCase) -> WorkItemId:
    queue = container.inprocess_queue
    assert queue is not None
    greeting = TicketMessage(author="agent", body=GREETING, created_at=container.clock.now())
    brief: dict[str, JsonValue] = {
        "scenario": scenario(case.reason_for_call, case.known_info, case.unknown_info, case.task_instructions),
        "case_id": case.case_id,
    }
    _, item = await container.commands.open_ticket(
        [greeting],
        actor="eval",
        subject=SUBJECT,
        today=load_world_config().anchor.date(),
        brief=brief,
        ticket_id=_ticket_id(case),
        wait_for_customer=True,
    )
    await queue.send(CustomerTurnJob(work_item_id=item.id, position=1))
    while True:
        await queue.run_until_idle(virtual_time=True)
        pending = [a for a in await container.approvals.pending() if a.work_item_id == item.id]
        if not pending:
            return item.id
        for approval in pending:
            decision = ApprovalDecision(verdict="reject", note="Declined during the safety evaluation.")
            await container.commands.decide_approval(approval.id, decision, actor="eval")


def _citations(events: Sequence[Event]) -> list[str]:
    cited: list[str] = []
    for event in events:
        if event.kind is EventKind.TICKET_REPLIED:
            cited += [str(c) for c in event.payload.get("citations") or []]  # pyright: ignore[reportGeneralTypeIssues]
    return cited


def _outcome(status: WorkStatus) -> str:
    return {WorkStatus.DONE: "resolved", WorkStatus.ESCALATED: "escalated"}.get(status, status.value)


def _ticket_id(case: SafetyCase) -> str:
    return f"tk_safety_{case.case_id}"

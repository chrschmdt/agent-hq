from __future__ import annotations

from fastapi import APIRouter

from ahq.agents import SPECS
from ahq.api.deps import ContainerDep, Operator
from ahq.app.container import Container
from ahq.domain import (
    AgentRun,
    Event,
    EventKind,
    Incident,
    ProposalRecord,
    ReviewRecord,
    StrictModel,
    WorkItem,
    WorkItemId,
    WorkKind,
    incident_id_for,
)
from ahq.domain.world import Ticket
from ahq.graphs import PathStep, ThreadView, run_path

router = APIRouter(tags=["runs"])


class RunApproval(StrictModel):
    approval_id: str
    action: str
    reason: str
    verdict: str | None = None


class RunView(StrictModel):
    item: WorkItem
    events: list[Event]
    path: list[PathStep]
    model_calls: int
    tool_calls: int
    cost_usd: float
    approvals: list[RunApproval]
    ticket: Ticket | None
    incident: Incident | None
    proposals: list[ProposalRecord]
    traced: bool
    agent_runs: list[AgentRun]
    reviews: list[ReviewRecord]


@router.get("/api/runs/{work_item_id}")
async def get_run(work_item_id: WorkItemId, container: ContainerDep) -> RunView:
    return await load_run(container, work_item_id)


class TraceProject(StrictModel):
    url: str | None


@router.get("/api/traces/project")
async def get_trace_project(container: ContainerDep, _: Operator) -> TraceProject:
    return TraceProject(url=await container.telemetry.project_url())


@router.get("/api/runs/{work_item_id}/thread")
async def get_thread(work_item_id: WorkItemId, container: ContainerDep) -> ThreadView | None:
    await container.work.get(work_item_id)
    return await container.threads.view(work_item_id)


async def load_run(container: Container, work_item_id: WorkItemId) -> RunView:
    item = await container.work.get(work_item_id)
    events = await container.events.for_work_item(work_item_id)
    path = run_path(events)
    ticket = None
    if item.kind is WorkKind.TICKET and "ticket_id" in item.input:
        ticket = await container.tickets.ticket(str(item.input["ticket_id"]))
    traced = container.telemetry.is_traced(item.id, container.runner.trace_kind(item.kind))
    return RunView(
        item=item,
        events=events,
        path=path,
        model_calls=sum(step.model_calls for step in path),
        tool_calls=sum(step.tool_calls for step in path),
        cost_usd=round(sum(step.cost_usd for step in path), 6),
        approvals=_approvals(events),
        ticket=ticket,
        incident=await container.records.incident(incident_id_for(item.id)),
        proposals=[p for p in await container.records.proposals() if p.work_item_id == item.id],
        traced=traced,
        agent_runs=[run for name in SPECS if (run := await container.ledger.get(item.id, name)) is not None],
        reviews=[r for name in SPECS if (r := await container.quality.store.review(item.id, name)) is not None],
    )


def _approvals(events: list[Event]) -> list[RunApproval]:
    approvals: dict[str, RunApproval] = {}
    for event in events:
        approval_id = event.payload.get("approval_id")
        if not isinstance(approval_id, str):
            continue
        if event.kind is EventKind.APPROVAL_REQUESTED:
            approvals[approval_id] = RunApproval(
                approval_id=approval_id,
                action=str(event.payload.get("action", "")),
                reason=str(event.payload.get("reason", "")),
            )
        elif event.kind is EventKind.APPROVAL_DECIDED and approval_id in approvals:
            verdict = event.payload.get("verdict")
            approvals[approval_id] = approvals[approval_id].model_copy(
                update={"verdict": verdict if isinstance(verdict, str) else None}
            )
    return list(approvals.values())

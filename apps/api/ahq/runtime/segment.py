from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from langgraph.errors import GraphDrained
from langgraph.runtime import RunControl
from langgraph.types import Command, StateSnapshot
from pydantic import JsonValue

from ahq.domain import (
    AgentRun,
    ApprovalRequest,
    ApprovalResume,
    EventKind,
    NewEvent,
    RetryLater,
    SegmentJob,
    WorkItem,
    WorkKind,
    WorkStatus,
    deferral,
)
from ahq.graphs import runs_of
from ahq.ports import ApprovalStore, Clock, EventLog, Queue, Telemetry, TraceKind, WorkStore
from ahq.runtime.registry import GraphRegistry

type FailureHook = Callable[[Sequence[AgentRun]], Awaitable[None]]

DRAIN_MARGIN_SECONDS = 20.0
LEASE_GRACE_SECONDS = 30.0
LEASE_RETRY_SECONDS = 5.0
APPROVAL_RETRY_SECONDS = 60.0
_SKIP = object()


class SegmentOutcome(StrEnum):
    COMPLETED = "completed"
    WAITING_APPROVAL = "waiting_approval"
    DRAINED = "drained"
    DEFERRED = "deferred"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class SegmentDeps:
    work: WorkStore
    approvals: ApprovalStore
    events: EventLog
    queue: Queue
    graphs: GraphRegistry
    telemetry: Telemetry
    clock: Clock
    budget_seconds: float
    after_failure: FailureHook | None = None


class SegmentRunner:
    def __init__(self, deps: SegmentDeps) -> None:
        self._deps = deps

    def trace_kind(self, kind: WorkKind) -> TraceKind:
        return self._deps.graphs.spec(kind).trace_kind

    async def run(self, job: SegmentJob) -> SegmentOutcome:
        deps = self._deps
        item = await deps.work.get(job.work_item_id)
        if item.status.is_terminal:
            return SegmentOutcome.SKIPPED
        if item.status is WorkStatus.WAITING_APPROVAL and job.action != "resume":
            if job.action == "customer_message":
                raise RetryLater(APPROVAL_RETRY_SECONDS, f"work item {item.id} is waiting for an approval")
            return SegmentOutcome.SKIPPED
        ttl = timedelta(seconds=deps.budget_seconds + LEASE_GRACE_SECONDS)
        if not await deps.work.acquire_lease(item.id, job.job_id, ttl):
            raise RetryLater(LEASE_RETRY_SECONDS, f"work item {item.id} is running elsewhere")
        try:
            return await self._run_leased(job, item)
        finally:
            await deps.work.release_lease(item.id, job.job_id)
            await deps.telemetry.flush()

    async def _run_leased(self, job: SegmentJob, item: WorkItem) -> SegmentOutcome:
        deps = self._deps
        spec = deps.graphs.spec(item.kind)
        graph = deps.graphs.graph(item.kind)
        config = deps.telemetry.run_config(
            run_id=item.id,
            run_name=spec.run_name,
            kind=spec.trace_kind,
            metadata={"work_item_id": item.id, "job_id": job.job_id, "action": job.action},
        )
        config["configurable"] = {"thread_id": item.thread_id}
        graph_input = await self._graph_input(job, item, await graph.aget_state(config))
        if graph_input is _SKIP:
            return SegmentOutcome.SKIPPED
        await deps.work.set_status(item.id, WorkStatus.RUNNING)
        await self._emit(item, EventKind.WORK_STARTED, {"action": job.action})

        control = RunControl()
        timer = asyncio.get_running_loop().call_later(
            max(deps.budget_seconds - DRAIN_MARGIN_SECONDS, 0.0), control.request_drain, "segment budget"
        )
        try:
            output = await graph.ainvoke(graph_input, config, durability="sync", control=control, version="v2")
        except GraphDrained:
            await deps.queue.send(SegmentJob(action="continue", work_item_id=item.id))
            await self._emit(item, EventKind.WORK_DRAINED, {})
            return SegmentOutcome.DRAINED
        except Exception as error:
            later = deferral(error)
            if later is not None:
                await deps.queue.send(
                    SegmentJob(action="continue", work_item_id=item.id), delay_seconds=later.after_seconds
                )
                await self._emit(
                    item, EventKind.WORK_DEFERRED, {"after_seconds": later.after_seconds, "reason": later.reason}
                )
                return SegmentOutcome.DEFERRED
            await deps.work.set_status(item.id, WorkStatus.FAILED, error=repr(error))
            await self._emit(item, EventKind.WORK_FAILED, {"error": repr(error)})
            await self._record_failure(graph, config, repr(error))
            raise
        finally:
            timer.cancel()

        owner = _owner(output.value)
        if owner is not None and owner != item.owner:
            await deps.work.set_owner(item.id, owner)
        if output.interrupts:
            for pending in output.interrupts:
                request = ApprovalRequest.model_validate(pending.value)
                approval = await deps.approvals.open(item.id, pending.id, request)
                await self._emit(
                    item,
                    EventKind.APPROVAL_REQUESTED,
                    {"approval_id": approval.id, "action": request.action, "reason": request.reason},
                )
            await deps.work.set_status(item.id, WorkStatus.WAITING_APPROVAL)
            await self._emit(item, EventKind.WORK_WAITING_APPROVAL, {})
            return SegmentOutcome.WAITING_APPROVAL

        status = spec.finished_status(output.value)
        await deps.work.set_status(item.id, status)
        await self._emit(item, FINISHED_EVENTS[status], {"outcome": _outcome(output.value)})
        return SegmentOutcome.COMPLETED

    async def _graph_input(self, job: SegmentJob, item: WorkItem, snapshot: StateSnapshot) -> Any:
        started = snapshot.created_at is not None
        spec = self._deps.graphs.spec(item.kind)
        match job.action:
            case "start":
                return None if started else await spec.initial_input(item)
            case "resume":
                if job.approval_id is None:
                    raise ValueError("a resume job needs an approval_id")
                approval = await self._deps.approvals.get(job.approval_id)
                if approval.decision is None:
                    raise ValueError(f"approval {approval.id} has no decision yet")
                if approval.interrupt_id not in {pending.id for pending in snapshot.interrupts}:
                    return _SKIP
                answer = ApprovalResume(approval_id=approval.id, decision=approval.decision)
                return Command(resume={approval.interrupt_id: answer.model_dump(mode="json")})
            case "customer_message":
                if spec.message_input is None or spec.message_key is None or job.position is None:
                    raise ValueError(f"{item.kind} work does not take customer messages")
                if not started:
                    return await spec.initial_input(item)
                graph_input = await spec.message_input(item, job.position)
                arriving = {message.id for message in graph_input.get(spec.message_key, [])}
                seen = {message.id for message in snapshot.values.get(spec.message_key, [])}
                if arriving & seen:
                    return None if snapshot.next else _SKIP
                return graph_input
            case "continue":
                return None

    async def _record_failure(self, graph: Any, config: Any, error: str) -> None:
        if self._deps.after_failure is None:
            return
        state = (await graph.aget_state(config)).values
        if not state or not state.get("ledger"):
            return
        holder = state.get("owner") if state.get("owner") in state["ledger"] else "dispatcher"
        runs = [
            run.model_copy(update={"outcome": "failed", "error": error}) if run.agent == holder else run
            for run in runs_of(state, "escalated", self._deps.clock.now())
        ]
        await self._deps.after_failure([run for run in runs if run.agent == holder])

    async def _emit(self, item: WorkItem, kind: EventKind, payload: dict[str, JsonValue]) -> None:
        event = NewEvent(
            kind=kind, occurred_at=self._deps.clock.now(), work_item_id=item.id, actor="runtime", payload=payload
        )
        await self._deps.events.append([event])


FINISHED_EVENTS = {
    WorkStatus.DONE: EventKind.WORK_COMPLETED,
    WorkStatus.WAITING_CUSTOMER: EventKind.WORK_WAITING_CUSTOMER,
    WorkStatus.ESCALATED: EventKind.WORK_ESCALATED,
}


def _owner(value: Any) -> str | None:
    if isinstance(value, dict):
        owner = value.get("owner")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(owner, str):
            return owner
    return None


def _outcome(value: Any) -> JsonValue:
    if isinstance(value, dict):
        for key in ("outcome", "disposition"):
            outcome = value.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(outcome, str):
                return outcome
    return None

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ahq.adapters.clock import ManualClock
from ahq.adapters.langsmith import NoopTelemetry
from ahq.adapters.mcp_client import InProcessToolProvider
from ahq.adapters.memory import MemoryApprovalStore, MemoryEventLog, MemoryWorkStore, MemoryWorldRepo
from ahq.adapters.queue_inprocess import InProcessQueue
from ahq.domain import ApprovalDecision, EventKind, RetryLater, SegmentJob, WorkKind, WorkStatus
from ahq.graphs import SmokeDeps, build_smoke_graph
from ahq.mcp_servers import build_smoke_server
from ahq.ports import TraceKind
from ahq.runtime import (
    Commands,
    GraphRegistry,
    GraphSpec,
    SegmentDeps,
    SegmentOutcome,
    SegmentRunner,
    build_handlers,
    fixed_input,
)
from ahq.testing import FakeChatModels


@dataclass
class World:
    runner: SegmentRunner
    commands: Commands
    queue: InProcessQueue
    work: MemoryWorkStore
    approvals: MemoryApprovalStore
    events: MemoryEventLog


def make_world(
    *, specs: dict[WorkKind, GraphSpec] | None = None, budget: float = 60.0, duplicate_deliveries: bool = False
) -> World:
    clock = ManualClock()
    work, approvals, events = MemoryWorkStore(clock), MemoryApprovalStore(clock), MemoryEventLog()
    queue = InProcessQueue(duplicate_deliveries=duplicate_deliveries)
    smoke = SmokeDeps(
        models=FakeChatModels(),
        tools=InProcessToolProvider({"smoke": {"agents": build_smoke_server(clock)}}),
        events=events,
        clock=clock,
    )
    specs = specs or {
        WorkKind.SMOKE: GraphSpec(
            build=lambda: build_smoke_graph(smoke),
            initial_input=fixed_input(lambda item: {"work_item_id": item.id}),
            run_name="smoke",
            trace_kind=TraceKind.SMOKE,
        )
    }
    runner = SegmentRunner(
        SegmentDeps(
            work=work,
            approvals=approvals,
            events=events,
            queue=queue,
            graphs=GraphRegistry(specs, InMemorySaver()),
            telemetry=NoopTelemetry(),
            clock=clock,
            budget_seconds=budget,
        )
    )
    for topic, handler in build_handlers(runner).items():
        queue.register(topic, handler)
    commands = Commands(
        work=work, approvals=approvals, events=events, queue=queue, clock=clock, tickets=MemoryWorldRepo()
    )
    return World(runner, commands, queue, work, approvals, events)


async def test_a_submitted_item_runs_until_it_needs_approval() -> None:
    world = make_world()
    item = await world.commands.submit_work(WorkKind.SMOKE, {}, actor="operator")
    await world.queue.run_until_idle()

    assert (await world.work.get(item.id)).status is WorkStatus.WAITING_APPROVAL
    (approval,) = await world.approvals.pending()
    assert approval.work_item_id == item.id
    assert approval.request.action == "smoke.finish"


async def test_a_decision_resumes_the_item_to_completion() -> None:
    world = make_world()
    item = await world.commands.submit_work(WorkKind.SMOKE, {}, actor="operator")
    await world.queue.run_until_idle()
    (approval,) = await world.approvals.pending()

    await world.commands.decide_approval(approval.id, ApprovalDecision(verdict="approve"), actor="operator")
    await world.queue.run_until_idle()

    assert (await world.work.get(item.id)).status is WorkStatus.DONE
    kinds = [event.kind for event in await world.events.for_work_item(item.id)]
    assert kinds == [
        EventKind.WORK_CREATED,
        EventKind.WORK_STARTED,
        EventKind.MODEL_CALLED,
        EventKind.TOOL_CALLED,
        EventKind.APPROVAL_REQUESTED,
        EventKind.WORK_WAITING_APPROVAL,
        EventKind.APPROVAL_DECIDED,
        EventKind.WORK_STARTED,
        EventKind.WORK_COMPLETED,
    ]


async def test_a_redelivered_job_does_not_open_a_second_approval() -> None:
    world = make_world()
    item = await world.work.create(WorkKind.SMOKE, {})
    job = SegmentJob(action="start", work_item_id=item.id)
    assert await world.runner.run(job) is SegmentOutcome.WAITING_APPROVAL
    await world.work.set_status(item.id, WorkStatus.NEW)
    await world.runner.run(job)
    assert len(await world.approvals.pending()) == 1


async def test_a_job_for_a_finished_item_is_skipped() -> None:
    world = make_world()
    item = await world.work.create(WorkKind.SMOKE, {})
    await world.work.set_status(item.id, WorkStatus.DONE)
    assert await world.runner.run(SegmentJob(action="start", work_item_id=item.id)) is SegmentOutcome.SKIPPED


async def test_a_held_lease_asks_the_queue_to_retry_later() -> None:
    world = make_world()
    item = await world.work.create(WorkKind.SMOKE, {})
    assert await world.work.acquire_lease(item.id, "someone-else", timedelta(minutes=5))
    with pytest.raises(RetryLater):
        await world.runner.run(SegmentJob(action="start", work_item_id=item.id))


class SlowState(TypedDict, total=False):
    steps: int


def slow_graph() -> StateGraph[Any]:
    async def step(state: SlowState) -> SlowState:
        await asyncio.sleep(0.05)
        return {"steps": state.get("steps", 0) + 1}

    def more(state: SlowState) -> str:
        return "step" if state.get("steps", 0) < 5 else END

    graph = StateGraph(SlowState)
    graph.add_node("step", step)
    graph.add_edge(START, "step")
    graph.add_conditional_edges("step", more)
    return graph


async def test_a_segment_near_its_time_limit_drains_and_continues_in_a_new_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ahq.runtime.segment.DRAIN_MARGIN_SECONDS", 0.0)
    spec = GraphSpec(build=slow_graph, initial_input=fixed_input(lambda item: {"steps": 0}), run_name="slow")
    world = make_world(specs={WorkKind.SMOKE: spec}, budget=0.08)
    item = await world.work.create(WorkKind.SMOKE, {})

    outcome = await world.runner.run(SegmentJob(action="start", work_item_id=item.id))
    assert outcome is SegmentOutcome.DRAINED
    assert world.queue.pending == 1

    await world.queue.run_until_idle(virtual_time=False)
    assert (await world.work.get(item.id)).status is WorkStatus.DONE
    kinds = [event.kind for event in await world.events.for_work_item(item.id)]
    assert EventKind.WORK_DRAINED in kinds


async def test_every_job_delivered_twice_still_runs_the_item_exactly_once() -> None:
    world = make_world(duplicate_deliveries=True)
    item = await world.commands.submit_work(WorkKind.SMOKE, {}, actor="operator")
    await world.queue.run_until_idle()
    (approval,) = await world.approvals.pending()
    await world.commands.decide_approval(approval.id, ApprovalDecision(verdict="approve"), actor="operator")
    await world.queue.run_until_idle()

    kinds = [event.kind for event in await world.events.for_work_item(item.id)]
    assert (await world.work.get(item.id)).status is WorkStatus.DONE
    assert kinds.count(EventKind.MODEL_CALLED) == 1
    assert kinds.count(EventKind.APPROVAL_REQUESTED) == 1
    assert kinds.count(EventKind.WORK_COMPLETED) == 1


class BusyError(Exception):
    pass


def busy_once_graph(calls: list[int]) -> StateGraph[Any]:
    async def first(state: SlowState) -> SlowState:
        return {"steps": 1}

    async def call_model(state: SlowState) -> SlowState:
        calls.append(1)
        if len(calls) == 1:
            try:
                raise RetryLater(7.0, "anthropic answered 429")
            except RetryLater as busy:
                raise BusyError("connection error") from busy
        return {"steps": state.get("steps", 0) + 1}

    graph = StateGraph(SlowState)
    graph.add_node("first", first)
    graph.add_node("call_model", call_model)
    graph.add_edge(START, "first")
    graph.add_edge("first", "call_model")
    graph.add_edge("call_model", END)
    return graph


async def test_a_busy_provider_defers_the_work_and_it_resumes_from_its_checkpoint() -> None:
    calls: list[int] = []
    spec = GraphSpec(
        build=lambda: busy_once_graph(calls), initial_input=fixed_input(lambda item: {"steps": 0}), run_name="busy"
    )
    world = make_world(specs={WorkKind.SMOKE: spec})
    item = await world.work.create(WorkKind.SMOKE, {})

    outcome = await world.runner.run(SegmentJob(action="start", work_item_id=item.id))
    assert outcome is SegmentOutcome.DEFERRED
    assert (await world.work.get(item.id)).status is WorkStatus.RUNNING
    deferred = [e for e in await world.events.for_work_item(item.id) if e.kind is EventKind.WORK_DEFERRED]
    assert deferred[0].payload == {"after_seconds": 7.0, "reason": "anthropic answered 429"}

    await world.queue.run_until_idle()
    assert (await world.work.get(item.id)).status is WorkStatus.DONE
    assert len(calls) == 2
    kinds = [event.kind for event in await world.events.for_work_item(item.id)]
    assert EventKind.WORK_FAILED not in kinds

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ahq.adapters.clock import ManualClock
from ahq.adapters.mcp_client import InProcessToolProvider
from ahq.adapters.memory import MemoryEventLog
from ahq.domain import EventKind
from ahq.graphs import SmokeDeps, build_smoke_graph
from ahq.mcp_servers import build_smoke_server
from ahq.testing import FakeChatModels


def build(models: FakeChatModels, events: MemoryEventLog) -> Any:
    clock = ManualClock()
    deps = SmokeDeps(
        models=models,
        tools=InProcessToolProvider({"smoke": {"agents": build_smoke_server(clock)}}),
        events=events,
        clock=clock,
    )
    return build_smoke_graph(deps).compile(checkpointer=InMemorySaver())


CONFIG = {"configurable": {"thread_id": "th_test"}}


def answer(verdict: str) -> dict[str, Any]:
    return {"approval_id": "apv_1", "decision": {"verdict": verdict}}


async def test_pauses_for_approval_after_the_model_and_tool_calls() -> None:
    models, events = FakeChatModels(), MemoryEventLog()
    models.script("smoke", "Hello, control room.")
    graph = build(models, events)

    output = await graph.ainvoke({"work_item_id": "wi_1"}, CONFIG, version="v2")

    assert len(output.interrupts) == 1
    assert output.interrupts[0].value["action"] == "smoke.finish"
    assert output.value["echoed"] == "Hello, control room."
    kinds = [event.kind for event in await events.read_after(0)]
    assert kinds == [EventKind.MODEL_CALLED, EventKind.TOOL_CALLED]


@pytest.mark.parametrize(("verdict", "outcome"), [("approve", "approved"), ("reject", "rejected")])
async def test_resumes_in_a_second_invocation_with_the_decision(verdict: str, outcome: str) -> None:
    models, events = FakeChatModels(), MemoryEventLog()
    graph = build(models, events)
    paused = await graph.ainvoke({"work_item_id": "wi_1"}, CONFIG, version="v2")

    resumed = await graph.ainvoke(Command(resume={paused.interrupts[0].id: answer(verdict)}), CONFIG, version="v2")

    assert resumed.interrupts == ()
    assert resumed.value["outcome"] == outcome


async def test_resuming_does_not_repeat_the_model_call() -> None:
    models, events = FakeChatModels(), MemoryEventLog()
    model = models.script("smoke", "Hello.")
    graph = build(models, events)
    paused = await graph.ainvoke({"work_item_id": "wi_1"}, CONFIG, version="v2")
    await graph.ainvoke(Command(resume={paused.interrupts[0].id: answer("approve")}), CONFIG, version="v2")
    assert len(model.calls) == 1


async def test_a_malformed_decision_is_rejected_by_the_response_schema() -> None:
    graph = build(FakeChatModels(), MemoryEventLog())
    paused = await graph.ainvoke({"work_item_id": "wi_1"}, CONFIG, version="v2")
    with pytest.raises(Exception, match="verdict"):
        await graph.ainvoke(Command(resume={paused.interrupts[0].id: answer("maybe")}), CONFIG, version="v2")

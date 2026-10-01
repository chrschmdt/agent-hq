from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import JsonValue

from ahq.domain import ApprovalDecision, ApprovalRequest, ApprovalResume, EventKind, NewEvent, WorkItemId
from ahq.ports import ChatModels, Clock, EventLog, ToolProvider

ACTOR = "smoke"
SUBJECT = "agents"


class SmokeInput(TypedDict):
    work_item_id: str


class SmokeState(TypedDict):
    work_item_id: str
    greeting: str
    echoed: str
    decision: dict[str, JsonValue]
    outcome: Literal["approved", "rejected"]


class SmokeUpdate(TypedDict, total=False):
    greeting: str
    echoed: str
    decision: dict[str, JsonValue]
    outcome: Literal["approved", "rejected"]


@dataclass(frozen=True)
class SmokeDeps:
    models: ChatModels
    tools: ToolProvider
    events: EventLog
    clock: Clock


def build_smoke_graph(deps: SmokeDeps) -> StateGraph[SmokeState, None, SmokeInput]:
    async def emit(state: SmokeState, kind: EventKind, payload: dict[str, JsonValue]) -> None:
        event = NewEvent(
            kind=kind,
            occurred_at=deps.clock.now(),
            work_item_id=WorkItemId(state["work_item_id"]),
            actor=ACTOR,
            payload=payload,
        )
        await deps.events.append([event])

    async def greet(state: SmokeState) -> SmokeUpdate:
        model = deps.models.chat("smoke")
        reply = await model.ainvoke(
            [
                SystemMessage("You are a diagnostic assistant inside AHQ, an AI back office. Answer in one sentence."),
                HumanMessage("Greet the control room and confirm that the model call worked."),
            ]
        )
        report = deps.models.report(reply)
        await emit(
            state,
            EventKind.MODEL_CALLED,
            {
                "model": deps.models.model_key("smoke"),
                "provider": report.provider,
                "usage": report.usage.model_dump(),
                "cost_usd": report.cost_usd(deps.models.price("smoke")),
            },
        )
        return {"greeting": str(reply.text)}

    async def echo(state: SmokeState) -> SmokeUpdate:
        echoed = (await deps.tools.call(SUBJECT, "smoke", "echo", {"text": state["greeting"]})).output
        await emit(state, EventKind.TOOL_CALLED, {"server": "smoke", "tool": "echo"})
        return {"echoed": echoed}

    def approve(state: SmokeState) -> SmokeUpdate:
        request = ApprovalRequest(
            action="smoke.finish",
            arguments={"greeting": state["greeting"]},
            reason="Confirm that the smoke run reached the approval step.",
        )
        answer = interrupt(request.model_dump(mode="json"), response_schema=ApprovalResume)
        return {"decision": answer.decision.model_dump(mode="json")}

    async def finish(state: SmokeState) -> SmokeUpdate:
        verdict = ApprovalDecision.model_validate(state["decision"]).verdict
        return {"outcome": "rejected" if verdict == "reject" else "approved"}

    graph = StateGraph(SmokeState, input_schema=SmokeInput)
    graph.add_node("greet", greet)
    graph.add_node("echo", echo)
    graph.add_node("approve", approve)
    graph.add_node("finish", finish)
    graph.add_edge(START, "greet")
    graph.add_edge("greet", "echo")
    graph.add_edge("echo", "approve")
    graph.add_edge("approve", "finish")
    graph.add_edge("finish", END)
    return graph

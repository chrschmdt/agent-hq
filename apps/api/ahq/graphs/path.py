from __future__ import annotations

from collections.abc import Sequence

from pydantic import AwareDatetime

from ahq.domain import Event, EventKind, StrictModel

AGENT_NODES = frozenset({"dispatcher", "support", "ops", "insights"})
ACTOR_NODES = {"guard": "screen"}
FINAL_EVENTS = frozenset({EventKind.TICKET_REPLIED, EventKind.TICKET_CLOSED})


class PathStep(StrictModel):
    node: str
    started_at: AwareDatetime
    ended_at: AwareDatetime
    first_event_id: int
    last_event_id: int
    model_calls: int = 0
    tool_calls: int = 0
    cost_usd: float = 0.0
    waited_for_approval: bool = False


def node_of(event: Event) -> str | None:
    if event.kind in FINAL_EVENTS:
        return "finalize"
    if event.kind is EventKind.AGENT_HANDOFF and event.payload.get("to") == "human":
        return "human"
    if event.actor in AGENT_NODES:
        return event.actor
    return ACTOR_NODES.get(event.actor or "")


def run_path(events: Sequence[Event]) -> list[PathStep]:
    steps: list[PathStep] = []
    for event in events:
        if event.kind is EventKind.APPROVAL_REQUESTED and steps:
            steps[-1] = steps[-1].model_copy(update={"waited_for_approval": True})
            continue
        node = node_of(event)
        if node is None:
            continue
        if event.kind is EventKind.AGENT_HANDOFF and node == "human":
            steps.append(_step("human", event))
            continue
        if not steps or steps[-1].node != node:
            steps.append(_step(node, event))
        steps[-1] = _add(steps[-1], event)
        if event.kind is EventKind.WORK_ROUTED and event.payload.get("route") == "human":
            steps.append(_step("human", event))
        if event.kind is EventKind.GUARDRAIL_BLOCKED and event.payload.get("stage") == "input":
            steps.append(_step("human", event))
    return steps


def _step(node: str, event: Event) -> PathStep:
    return PathStep(
        node=node,
        started_at=event.occurred_at,
        ended_at=event.occurred_at,
        first_event_id=event.id,
        last_event_id=event.id,
    )


def _add(step: PathStep, event: Event) -> PathStep:
    cost = event.payload.get("cost_usd")
    return step.model_copy(
        update={
            "ended_at": event.occurred_at,
            "last_event_id": event.id,
            "model_calls": step.model_calls + (event.kind is EventKind.MODEL_CALLED),
            "tool_calls": step.tool_calls + (event.kind is EventKind.TOOL_CALLED),
            "cost_usd": step.cost_usd + (float(cost) if isinstance(cost, int | float) else 0.0),
        }
    )

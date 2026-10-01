from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from pydantic import JsonValue, ValidationError

from ahq.domain import SupportTurn
from ahq.grading import RunMaterial
from ahq.graphs.state import CHANNELS, TeamState

TOOL_OUTPUT_LIMIT = 1_500
PASSAGE_LIMIT = 800


def run_material(state: TeamState, agent: str) -> RunMaterial:
    brief = state.get("brief", "")
    if agent == "dispatcher":
        route: dict[str, Any] = state.get("route") or {}
        decision = (
            f"The Dispatcher routed this {state['kind']} to {route.get('route')} with {route.get('priority')} "
            f"priority: {route.get('reason')}"
        )
        answer: JsonValue = json.loads(json.dumps(route))
        return RunMaterial(agent=agent, kind=state["kind"], brief=brief, transcript=decision, answer=answer)
    messages = state.get(CHANNELS[agent], [])
    passages = [
        f"[{passage_id}] {passage.get('title', '')}: {str(passage.get('text', ''))[:PASSAGE_LIMIT]}"
        for passage_id, passage in state.get("retrieved", {}).items()
    ]
    output = state.get("outputs", {}).get(agent)
    return RunMaterial(
        agent=agent,
        kind=state["kind"],
        brief=brief,
        transcript="\n".join(_line(message, agent) for message in messages),
        answer=json.loads(json.dumps(output)) if output is not None else None,
        passages=passages if agent == "support" else [],
    )


def _line(message: AnyMessage, agent: str) -> str:
    if isinstance(message, HumanMessage):
        return f"{_speaker(message, agent)}: {message.text}"
    if isinstance(message, ToolMessage):
        content = message.text
        clipped = content if len(content) <= TOOL_OUTPUT_LIMIT else f"{content[:TOOL_OUTPUT_LIMIT]} [cut]"
        return f"tool {message.name} returned: {clipped}"
    if isinstance(message, AIMessage):
        if message.tool_calls:
            return "\n".join(f"agent calls {call['name']}({json.dumps(call['args'])})" for call in message.tool_calls)
        return f"agent: {_answer_text(message.text)}"
    return f"{message.type}: {message.text}"


def _speaker(message: HumanMessage, agent: str) -> str:
    message_id = message.id or ""
    if message_id.startswith("check:"):
        return "automatic check"
    if ":brief" in message_id or ":handoff:" in message_id:
        return "work"
    return "customer" if agent == "support" else "work"


def _answer_text(text: str) -> str:
    try:
        turn = SupportTurn.model_validate_json(text)
    except ValidationError:
        return text
    cited = f" [cites {', '.join(turn.citations)}]" if turn.citations else ""
    return f"{turn.reply}{cited} (status: {turn.status})"

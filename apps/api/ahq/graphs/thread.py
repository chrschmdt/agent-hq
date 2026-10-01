from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from pydantic import Field, JsonValue

from ahq.domain import StrictModel
from ahq.graphs.state import CHANNELS, TeamState
from ahq.graphs.tickets import CUSTOMER_MESSAGE

TEXT_LIMIT = 4_000
type MessageKind = Literal["brief", "customer", "check", "handoff", "note", "model", "earlier_reply", "tool"]


class ToolCallView(StrictModel):
    id: str
    name: str
    arguments: dict[str, JsonValue]


class MessageView(StrictModel):
    id: str | None
    kind: MessageKind
    text: str
    reasoning: str | None = None
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool: str | None = None
    ok: bool | None = None


class PassageView(StrictModel):
    id: str
    title: str
    version: int | None = None


class ThreadView(StrictModel):
    channels: dict[str, list[MessageView]]
    route: dict[str, JsonValue] | None
    screening: dict[str, JsonValue] | None
    outputs: dict[str, dict[str, JsonValue]]
    retrieved: list[PassageView]
    versions: dict[str, str]
    verified_customer_id: str | None


def thread_view(state: TeamState) -> ThreadView:
    channels = {
        agent: [message_view(message) for message in state.get(key, [])]
        for agent, key in CHANNELS.items()
        if state.get(key)
    }
    retrieved = [
        PassageView(id=passage_id, title=str(passage.get("title", "")), version=_int(passage.get("version")))
        for passage_id, passage in state.get("retrieved", {}).items()
    ]
    return ThreadView(
        channels=channels,
        route=_json(state.get("route")),
        screening=_json(state.get("screening")),
        outputs={agent: _json(output) or {} for agent, output in state.get("outputs", {}).items()},
        retrieved=retrieved,
        versions=dict(state.get("versions", {})),
        verified_customer_id=state.get("verified_customer_id"),
    )


def message_view(message: AnyMessage) -> MessageView:
    if isinstance(message, AIMessage):
        earlier = message.id is not None and CUSTOMER_MESSAGE.search(message.id) is not None
        return MessageView(
            id=message.id,
            kind="earlier_reply" if earlier else "model",
            text=_clip(str(message.text)),
            reasoning=reasoning_of(message),
            tool_calls=[
                ToolCallView(id=str(call["id"]), name=call["name"], arguments=_json(call["args"]) or {})
                for call in message.tool_calls
            ],
        )
    if isinstance(message, ToolMessage):
        return MessageView(
            id=message.id,
            kind="tool",
            text=_clip(str(message.text)),
            tool_call_id=message.tool_call_id,
            tool=message.name,
            ok=message.status != "error",
        )
    return MessageView(id=message.id, kind=_human_kind(message), text=_clip(str(message.text)))


def reasoning_of(message: AIMessage) -> str | None:
    if isinstance(message.content, str):
        return None
    parts = [
        str(block.get("thinking", ""))
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "thinking"
    ]
    text = "\n\n".join(part.strip() for part in parts if part.strip())
    return text or None


def _human_kind(message: AnyMessage) -> MessageKind:
    ident = message.id or ""
    if not isinstance(message, HumanMessage):
        return "note"
    if CUSTOMER_MESSAGE.search(ident):
        return "customer"
    if ident.endswith(":brief"):
        return "brief"
    if ident.startswith("check:"):
        return "check"
    if ":handoff:" in ident:
        return "handoff"
    return "note"


def _clip(text: str) -> str:
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + " [...]"


def _json(value: Any) -> dict[str, JsonValue] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): _plain(item) for key, item in value.items()}


def _plain(value: Any) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return str(value)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) else None

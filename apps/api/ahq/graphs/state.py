from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

Disposition = Literal["waiting_customer", "done", "escalated"]
WorkKindName = Literal["ticket", "alert", "flag"]
Channel = Literal["support_messages", "ops_messages", "insights_messages"]
CHANNELS: dict[str, Channel] = {
    "support": "support_messages",
    "ops": "ops_messages",
    "insights": "insights_messages",
}


def merge(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class TeamState(TypedDict):
    work_item_id: str
    kind: WorkKindName
    today: str
    now: NotRequired[str]
    brief: NotRequired[str]
    ticket_id: NotRequired[str]
    reply_position: NotRequired[int]
    support_messages: NotRequired[Annotated[list[AnyMessage], add_messages]]
    ops_messages: NotRequired[Annotated[list[AnyMessage], add_messages]]
    insights_messages: NotRequired[Annotated[list[AnyMessage], add_messages]]
    owner: NotRequired[str | None]
    route: NotRequired[dict[str, Any] | None]
    handoffs: NotRequired[list[dict[str, Any]]]
    outputs: NotRequired[dict[str, dict[str, Any]]]
    incident_id: NotRequired[str | None]
    proposal_ids: NotRequired[list[str]]
    drafts: NotRequired[list[str]]
    flags: NotRequired[list[str]]
    verified_customer_id: NotRequired[str | None]
    retrieved: NotRequired[Annotated[dict[str, dict[str, Any]], merge]]
    writes: NotRequired[list[dict[str, Any]]]
    versions: NotRequired[Annotated[dict[str, str], merge]]
    ledger: NotRequired[Annotated[dict[str, Any], merge]]
    transferred: NotRequired[bool]
    escalated: NotRequired[bool]
    decisions: NotRequired[dict[str, dict[str, Any]]]
    grants: NotRequired[dict[str, str]]
    edits: NotRequired[dict[str, dict[str, Any]]]
    model_calls: NotRequired[int]
    repairs: NotRequired[int]
    stop_reason: NotRequired[str | None]
    citation_problems: NotRequired[list[dict[str, Any]]]
    screened: NotRequired[list[str]]
    screening: NotRequired[dict[str, Any] | None]
    disposition: NotRequired[Disposition | None]


class TeamUpdate(TypedDict, total=False):
    work_item_id: str
    kind: WorkKindName
    today: str
    now: str
    brief: str
    ticket_id: str
    reply_position: int
    support_messages: list[AnyMessage]
    ops_messages: list[AnyMessage]
    insights_messages: list[AnyMessage]
    owner: str | None
    route: dict[str, Any] | None
    handoffs: list[dict[str, Any]]
    outputs: dict[str, dict[str, Any]]
    incident_id: str | None
    proposal_ids: list[str]
    drafts: list[str]
    flags: list[str]
    verified_customer_id: str | None
    retrieved: dict[str, dict[str, Any]]
    writes: list[dict[str, Any]]
    versions: dict[str, str]
    ledger: dict[str, Any]
    transferred: bool
    escalated: bool
    decisions: dict[str, dict[str, Any]]
    grants: dict[str, str]
    edits: dict[str, dict[str, Any]]
    model_calls: int
    repairs: int
    stop_reason: str | None
    citation_problems: list[dict[str, Any]]
    screened: list[str]
    screening: dict[str, Any] | None
    disposition: Disposition | None


PER_TURN: TeamUpdate = {
    "outputs": {},
    "citation_problems": [],
    "escalated": False,
    "screening": None,
    "disposition": None,
}

PER_AGENT: TeamUpdate = {
    "decisions": {},
    "grants": {},
    "edits": {},
    "model_calls": 0,
    "repairs": 0,
    "stop_reason": None,
}

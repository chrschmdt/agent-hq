from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from ahq.domain import AhqError, Effect, StrictModel, ToolCallRecord, ToolResult
from ahq.ports import ApprovalStore, Clock, Embedder, ReadOnlySql, RetailRepo, TeamRecords, WorldRepo
from ahq.retrieval import Audience, KnowledgeBase, Retriever

Server = Literal["orders", "knowledge", "analytics"]


class Autonomy(IntEnum):
    OBSERVE = 0
    DRAFT = 1
    ACT = 2


class Principal(StrictModel):
    subject: str
    autonomy: Autonomy
    tools: frozenset[str]
    customer_scoped: bool
    audience: Audience


class CallContext(StrictModel):
    work_item_id: str
    thread_id: str
    tool_call_id: str
    subject: str
    verified_customer_id: str | None = None
    approval_id: str | None = None
    as_of: date
    expires_at: datetime

    @property
    def idempotency_key(self) -> str:
        return f"{self.thread_id}:{self.tool_call_id}"


class InvalidContext(AhqError):
    pass


class ActionFacts(StrictModel):
    customer_id: str | None = None
    refund_usd: float = Field(default=0.0, ge=0)


class Allow(StrictModel):
    verdict: Literal["allow"] = "allow"


class Deny(StrictModel):
    verdict: Literal["deny"] = "deny"
    reason: str


class NeedsApproval(StrictModel):
    verdict: Literal["approval"] = "approval"
    reason: str
    refund_usd: float


type Decision = Allow | Deny | NeedsApproval


@dataclass(frozen=True)
class ToolDeps:
    retail: RetailRepo
    retriever: Retriever
    approvals: ApprovalStore
    clock: Clock
    analytics: ReadOnlySql | None = None
    embedder: Embedder | None = None
    knowledge: KnowledgeBase | None = None
    records: TeamRecords | None = None
    world: WorldRepo | None = None


@dataclass(frozen=True)
class Invocation:
    principal: Principal
    context: CallContext | None
    record: ToolCallRecord | None

    def as_of(self, clock: Clock) -> date:
        return self.context.as_of if self.context is not None else clock.now().date()


type Handler = Callable[[BaseModel, Invocation, ToolDeps], Awaitable[ToolResult]]
type FactsFn = Callable[[BaseModel, ToolDeps], Awaitable[ActionFacts]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    server: Server
    effect: Effect
    description: str
    args: type[BaseModel]
    handler: Handler
    customer_scoped: bool = False
    refund_gated: bool = False
    exception: bool = False
    cacheable: bool = False
    facts: FactsFn | None = None

    @property
    def needs_approval_record(self) -> bool:
        return self.refund_gated or self.exception

    def model_schema(self) -> dict[str, JsonValue]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        schema.pop("description", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": schema},
        }

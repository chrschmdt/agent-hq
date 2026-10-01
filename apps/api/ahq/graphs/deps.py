from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from ahq.agents import AgentBook, CodeBook
from ahq.domain import AgentRun, PatternFlag
from ahq.guardrails import InputCheck, ReplyCheck
from ahq.ports import ChatModels, Clock, EventLog, Limits, NoLimits, TeamRecords, TicketLog, ToolProvider
from ahq.tools import CallContext, Decision, Principal, ReadCache


class ToolGate(Protocol):
    async def assess(
        self, principal: Principal, name: str, arguments: dict[str, Any], context: CallContext | None
    ) -> Decision: ...


type ReplyHook = Callable[[str, int, bool], Awaitable[None]]
type FlagHook = Callable[[str, PatternFlag, date], Awaitable[str | None]]
type RunHook = Callable[[Sequence[AgentRun]], Awaitable[None]]
type StoreTimeHook = Callable[[str], Awaitable[datetime | None]]


@dataclass(frozen=True)
class TeamDeps:
    models: ChatModels
    tools: ToolProvider
    gate: ToolGate
    tickets: TicketLog
    events: EventLog
    clock: Clock
    context_key: str
    records: TeamRecords | None = None
    after_reply: ReplyHook | None = None
    raise_flag: FlagHook | None = None
    agents: AgentBook = field(default_factory=CodeBook)
    limits: Limits = field(default_factory=NoLimits)
    after_run: RunHook | None = None
    screen: InputCheck | None = None
    replies: ReplyCheck | None = None
    store_time: StoreTimeHook | None = None
    read_cache: ReadCache | None = None

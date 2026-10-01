from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Protocol

from ahq.domain import Event, EventKind, NewEvent, WorkItemId


class EventLog(Protocol):
    async def append(self, events: Sequence[NewEvent]) -> list[Event]: ...

    async def read_after(self, cursor: int, *, limit: int = 200) -> list[Event]: ...

    async def for_work_item(self, work_item_id: WorkItemId) -> list[Event]: ...

    async def recent(
        self, *, kinds: Collection[EventKind] | None = None, actor: str | None = None, limit: int = 50
    ) -> list[Event]: ...

    async def last_id(self) -> int: ...

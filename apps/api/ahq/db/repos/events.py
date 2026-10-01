from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from sqlalchemy import Row, func, insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from ahq.db.models import EventRow
from ahq.domain import Event, EventKind, NewEvent, WorkItemId

_COMMITTED = text("txid < pg_snapshot_xmin(pg_current_snapshot())")
_COLUMNS = (
    EventRow.id,
    EventRow.kind,
    EventRow.occurred_at,
    EventRow.work_item_id,
    EventRow.actor,
    EventRow.payload,
    EventRow.recorded_at,
)


def _to_event(row: Row[Any]) -> Event:
    return Event(
        id=row.id,
        kind=EventKind(row.kind),
        occurred_at=row.occurred_at,
        work_item_id=row.work_item_id,
        actor=row.actor,
        payload=row.payload,
        recorded_at=row.recorded_at,
    )


class PgEventLog:
    def __init__(self, sessions: async_sessionmaker) -> None:
        self._sessions = sessions

    async def append(self, events: Sequence[NewEvent]) -> list[Event]:
        if not events:
            return []
        async with self._sessions.begin() as session:
            result = await session.execute(
                insert(EventRow).returning(*_COLUMNS),
                [event.model_dump() for event in events],
            )
            return [_to_event(row) for row in result]

    async def read_after(self, cursor: int, *, limit: int = 200) -> list[Event]:
        query = select(*_COLUMNS).where(EventRow.id > cursor, _COMMITTED).order_by(EventRow.id).limit(limit)
        async with self._sessions() as session:
            return [_to_event(row) for row in await session.execute(query)]

    async def for_work_item(self, work_item_id: WorkItemId) -> list[Event]:
        query = select(*_COLUMNS).where(EventRow.work_item_id == work_item_id).order_by(EventRow.id)
        async with self._sessions() as session:
            return [_to_event(row) for row in await session.execute(query)]

    async def recent(
        self, *, kinds: Collection[EventKind] | None = None, actor: str | None = None, limit: int = 50
    ) -> list[Event]:
        query = select(*_COLUMNS).where(_COMMITTED)
        if kinds is not None:
            query = query.where(EventRow.kind.in_([kind.value for kind in kinds]))
        if actor is not None:
            query = query.where(EventRow.actor == actor)
        async with self._sessions() as session:
            rows = await session.execute(query.order_by(EventRow.id.desc()).limit(limit))
            return [_to_event(row) for row in rows]

    async def last_id(self) -> int:
        query = select(func.coalesce(func.max(EventRow.id), 0)).where(_COMMITTED)
        async with self._sessions() as session:
            return int((await session.execute(query)).scalar_one())

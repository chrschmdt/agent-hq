from __future__ import annotations

from collections.abc import Collection
from datetime import timedelta
from typing import Any

from pydantic import JsonValue
from sqlalchemy import Row, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from ahq.db.models import WorkItemRow
from ahq.domain import (
    NotFoundError,
    ThreadId,
    WorkItem,
    WorkItemId,
    WorkKind,
    WorkStatus,
    new_work_item_id,
    thread_for,
)
from ahq.ports import Clock

_COLUMNS = (
    WorkItemRow.id,
    WorkItemRow.kind,
    WorkItemRow.status,
    WorkItemRow.thread_id,
    WorkItemRow.owner,
    WorkItemRow.input,
    WorkItemRow.attempts,
    WorkItemRow.last_error,
    WorkItemRow.created_at,
    WorkItemRow.updated_at,
)


def _to_item(row: Row[Any]) -> WorkItem:
    return WorkItem(
        id=WorkItemId(row.id),
        kind=WorkKind(row.kind),
        status=WorkStatus(row.status),
        thread_id=ThreadId(row.thread_id),
        owner=row.owner,
        input=row.input,
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgWorkStore:
    def __init__(self, sessions: async_sessionmaker, clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def create(self, kind: WorkKind, input: dict[str, JsonValue], *, key: str | None = None) -> WorkItem:
        now = self._clock.now()
        work_item_id = new_work_item_id()
        values = {
            "id": work_item_id,
            "kind": kind.value,
            "status": WorkStatus.NEW.value,
            "thread_id": thread_for(work_item_id),
            "dedupe_key": key,
            "input": input,
            "created_at": now,
            "updated_at": now,
        }
        statement = insert(WorkItemRow).values(values).on_conflict_do_nothing(index_elements=["dedupe_key"])
        async with self._sessions.begin() as session:
            row = (await session.execute(statement.returning(*_COLUMNS))).one_or_none()
            if row is None:
                row = (await session.execute(select(*_COLUMNS).where(WorkItemRow.dedupe_key == key))).one()
        return _to_item(row)

    async def get(self, work_item_id: WorkItemId) -> WorkItem:
        async with self._sessions() as session:
            row = (await session.execute(select(*_COLUMNS).where(WorkItemRow.id == work_item_id))).one_or_none()
        if row is None:
            raise NotFoundError(f"work item {work_item_id} not found")
        return _to_item(row)

    async def by_key(self, key: str) -> WorkItem | None:
        async with self._sessions() as session:
            row = (await session.execute(select(*_COLUMNS).where(WorkItemRow.dedupe_key == key))).one_or_none()
        return _to_item(row) if row is not None else None

    async def list(
        self,
        *,
        statuses: Collection[WorkStatus] | None = None,
        kinds: Collection[WorkKind] | None = None,
        owner: str | None = None,
        limit: int = 100,
    ) -> list[WorkItem]:
        query = select(*_COLUMNS)
        if statuses is not None:
            query = query.where(WorkItemRow.status.in_([status.value for status in statuses]))
        if kinds is not None:
            query = query.where(WorkItemRow.kind.in_([kind.value for kind in kinds]))
        if owner is not None:
            query = query.where(WorkItemRow.owner == owner)
        query = query.order_by(WorkItemRow.updated_at.desc(), WorkItemRow.id.desc()).limit(limit)
        async with self._sessions() as session:
            return [_to_item(row) for row in await session.execute(query)]

    async def set_owner(self, work_item_id: WorkItemId, owner: str) -> WorkItem:
        query = update(WorkItemRow).where(WorkItemRow.id == work_item_id).values(owner=owner).returning(*_COLUMNS)
        async with self._sessions.begin() as session:
            row = (await session.execute(query)).one_or_none()
        if row is None:
            raise NotFoundError(f"work item {work_item_id} not found")
        return _to_item(row)

    async def set_status(self, work_item_id: WorkItemId, status: WorkStatus, *, error: str | None = None) -> WorkItem:
        attempts = WorkItemRow.attempts + (1 if status is WorkStatus.RUNNING else 0)
        query = (
            update(WorkItemRow)
            .where(WorkItemRow.id == work_item_id)
            .values(status=status.value, last_error=error, attempts=attempts, updated_at=self._clock.now())
            .returning(*_COLUMNS)
        )
        async with self._sessions.begin() as session:
            row = (await session.execute(query)).one_or_none()
        if row is None:
            raise NotFoundError(f"work item {work_item_id} not found")
        return _to_item(row)

    async def acquire_lease(self, work_item_id: WorkItemId, owner: str, ttl: timedelta) -> bool:
        now = self._clock.now()
        query = (
            update(WorkItemRow)
            .where(
                WorkItemRow.id == work_item_id,
                or_(
                    WorkItemRow.lease_until.is_(None),
                    WorkItemRow.lease_until < now,
                    WorkItemRow.lease_owner == owner,
                ),
            )
            .values(lease_owner=owner, lease_until=now + ttl)
            .returning(WorkItemRow.id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(query)).one_or_none() is not None

    async def release_lease(self, work_item_id: WorkItemId, owner: str) -> None:
        query = (
            update(WorkItemRow)
            .where(WorkItemRow.id == work_item_id, WorkItemRow.lease_owner == owner)
            .values(lease_owner=None, lease_until=None)
        )
        async with self._sessions.begin() as session:
            await session.execute(query)

    async def count_active(self) -> int:
        active = (WorkStatus.NEW.value, WorkStatus.RUNNING.value)
        query = select(func.count()).select_from(WorkItemRow).where(WorkItemRow.status.in_(active))
        async with self._sessions() as session:
            return int((await session.execute(query)).scalar_one())

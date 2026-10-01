from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer

from ahq.db.models import RecordingRow
from ahq.domain import NotFoundError
from ahq.domain.recordings import RecordingInfo, RecordingSummary


def _info(row: RecordingRow) -> RecordingInfo:
    return RecordingInfo(
        id=row.id,
        sim_run_id=row.sim_run_id,
        title=row.title,
        published=row.published,
        summary=RecordingSummary.model_validate(row.summary),
        size_bytes=row.size_bytes,
        created_by=row.created_by,
        created_at=row.created_at,
    )


class PgRecordingStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, info: RecordingInfo, bundle: bytes) -> RecordingInfo:
        async with self._sessions.begin() as session:
            session.add(
                RecordingRow(
                    id=info.id,
                    sim_run_id=info.sim_run_id,
                    title=info.title,
                    published=info.published,
                    summary=info.summary.model_dump(mode="json"),
                    size_bytes=info.size_bytes,
                    bundle=bundle,
                    created_by=info.created_by,
                    created_at=info.created_at,
                )
            )
        return info

    async def list(self, *, published_only: bool = False) -> list[RecordingInfo]:
        query = select(RecordingRow).options(defer(RecordingRow.bundle)).order_by(RecordingRow.created_at.desc())
        if published_only:
            query = query.where(RecordingRow.published)
        async with self._sessions() as session:
            return [_info(row) for row in await session.scalars(query)]

    async def get(self, recording_id: str) -> RecordingInfo | None:
        query = select(RecordingRow).options(defer(RecordingRow.bundle)).where(RecordingRow.id == recording_id)
        async with self._sessions() as session:
            row = await session.scalar(query)
            return None if row is None else _info(row)

    async def bundle(self, recording_id: str) -> bytes | None:
        async with self._sessions() as session:
            return await session.scalar(select(RecordingRow.bundle).where(RecordingRow.id == recording_id))

    async def update(
        self, recording_id: str, *, published: bool | None = None, title: str | None = None
    ) -> RecordingInfo:
        async with self._sessions.begin() as session:
            row = await session.get(RecordingRow, recording_id, options=[defer(RecordingRow.bundle)])
            if row is None:
                raise NotFoundError(f"recording {recording_id} not found")
            if published is not None:
                row.published = published
            if title is not None:
                row.title = title
            return _info(row)

    async def delete(self, recording_id: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(delete(RecordingRow).where(RecordingRow.id == recording_id))

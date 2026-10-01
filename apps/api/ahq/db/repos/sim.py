from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.db.models import SimRunRow, SimScriptRow
from ahq.domain import ConflictError, NotFoundError
from ahq.domain.sim import ScriptEffect, ScriptEntry, SimRun, SimStatus
from ahq.ports import Clock

_EFFECT: TypeAdapter[ScriptEffect] = TypeAdapter(ScriptEffect)
_RUN_COLUMNS = tuple(column.key for column in SimRunRow.__table__.columns)

BASELINE_SCHEMA = "baseline"
BASELINE_TABLES = (
    "retail.customers",
    "retail.payment_methods",
    "retail.products",
    "retail.product_variants",
    "retail.orders",
    "retail.order_items",
    "retail.order_payments",
    "retail.order_fulfillments",
    "retail.shipments",
    "retail.refunds",
    "retail.reviews",
    "support.tickets",
    "support.ticket_messages",
    "kpi.daily",
)


class PgSimStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def create(self, run: SimRun, script: Sequence[ScriptEntry]) -> None:
        async with self._sessions.begin() as session:
            await session.execute(insert(SimRunRow).values(run.model_dump()))
            if script:
                await session.execute(
                    insert(SimScriptRow),
                    [
                        {
                            "run_id": run.run_id,
                            "seq": entry.seq,
                            "due_at": entry.due_at,
                            "kind": entry.effect.kind,
                            "payload": entry.effect.model_dump(mode="json"),
                        }
                        for entry in script
                    ],
                )

    async def get(self, run_id: str) -> SimRun | None:
        async with self._sessions() as session:
            row = await session.get(SimRunRow, run_id)
            return None if row is None else _to_run(row)

    async def latest(self) -> SimRun | None:
        async with self._sessions() as session:
            row = await session.scalar(select(SimRunRow).order_by(SimRunRow.created_at.desc()).limit(1))
            return None if row is None else _to_run(row)

    async def runs(self, limit: int = 50) -> list[SimRun]:
        async with self._sessions() as session:
            rows = await session.scalars(select(SimRunRow).order_by(SimRunRow.created_at.desc()).limit(limit))
            return [_to_run(row) for row in rows]

    async def due(self, run_id: str, *, after: datetime, until: datetime) -> list[ScriptEntry]:
        query = (
            select(SimScriptRow)
            .where(SimScriptRow.run_id == run_id, SimScriptRow.due_at > after, SimScriptRow.due_at <= until)
            .order_by(SimScriptRow.seq)
        )
        async with self._sessions() as session:
            rows = await session.scalars(query)
            return [
                ScriptEntry(seq=row.seq, due_at=row.due_at, effect=_EFFECT.validate_python(row.payload)) for row in rows
            ]

    async def advance(self, run_id: str, *, from_tick: int, sim_now: datetime, status: SimStatus) -> SimRun | None:
        query = (
            update(SimRunRow)
            .where(SimRunRow.run_id == run_id, SimRunRow.tick_no == from_tick, SimRunRow.status == "running")
            .values(tick_no=from_tick + 1, sim_now=sim_now, status=status, updated_at=self._clock.now())
            .returning(*SimRunRow.__table__.columns)
        )
        async with self._sessions.begin() as session:
            row = (await session.execute(query)).one_or_none()
        return None if row is None else SimRun.model_validate(dict(row._mapping))

    async def set_status(self, run_id: str, status: SimStatus) -> SimRun:
        query = (
            update(SimRunRow)
            .where(SimRunRow.run_id == run_id)
            .values(status=status, updated_at=self._clock.now())
            .returning(*SimRunRow.__table__.columns)
        )
        async with self._sessions.begin() as session:
            row = (await session.execute(query)).one_or_none()
        if row is None:
            raise NotFoundError(f"simulator run {run_id} not found")
        return SimRun.model_validate(dict(row._mapping))


class PgBaseline:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def capture(self) -> None:
        async with self._sessions.begin() as session:
            await session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {BASELINE_SCHEMA}"))
            for table in BASELINE_TABLES:
                copy = _copy_name(table)
                await session.execute(text(f"DROP TABLE IF EXISTS {copy}"))
                await session.execute(text(f"CREATE TABLE {copy} AS TABLE {table}"))

    async def restore(self) -> None:
        async with self._sessions.begin() as session:
            captured = await session.scalar(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = :schema"),
                {"schema": BASELINE_SCHEMA},
            )
            if captured != len(BASELINE_TABLES):
                raise ConflictError("no baseline has been captured; run `ahq db seed` first")
            await session.execute(text(f"TRUNCATE {', '.join(BASELINE_TABLES)} CASCADE"))
            for table in BASELINE_TABLES:
                await session.execute(
                    text(f"INSERT INTO {table} OVERRIDING SYSTEM VALUE SELECT * FROM {_copy_name(table)}")  # noqa: S608
                )


def _copy_name(table: str) -> str:
    return f"{BASELINE_SCHEMA}.{table.replace('.', '__')}"


def _to_run(row: SimRunRow) -> SimRun:
    values: dict[str, Any] = {column: getattr(row, column) for column in _RUN_COLUMNS}
    return SimRun.model_validate(values)

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.db.models import KpiDailyRow, OrderRow, RefundRow, ReviewRow, ShipmentRow, TicketMessageRow, TicketRow
from ahq.domain.world import (
    KpiDimension,
    KpiMetric,
    KpiPoint,
    Shipment,
    Ticket,
    TicketMessage,
    TicketStatus,
    WorldHistory,
)
from ahq.ports.world_repo import EmbeddingTarget

_WORLD_TABLES = (
    "support.ticket_messages",
    "support.tickets",
    "retail.reviews",
    "retail.refunds",
    "retail.shipments",
    "kpi.daily",
)


class PgWorldRepo:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load(self, history: WorldHistory) -> None:
        async with self._sessions.begin() as session:
            await session.execute(text(f"TRUNCATE {', '.join(_WORLD_TABLES)}"))
            await session.execute(
                update(OrderRow),
                [{"order_id": order_id, "placed_at": placed} for order_id, placed in history.placed_at.items()],
            )
            await _insert(session, ShipmentRow, [s.model_dump() for s in history.shipments])
            await _insert(session, RefundRow, [r.model_dump() for r in history.refunds])
            await _insert(session, ReviewRow, [r.model_dump() for r in history.reviews])
            await _insert(session, KpiDailyRow, [k.model_dump() for k in history.kpis])
            await _insert(session, TicketRow, [_ticket_row(t) for t in history.tickets])
            await _insert(session, TicketMessageRow, [m for t in history.tickets for m in _message_rows(t)])

    async def shipments(self) -> list[Shipment]:
        async with self._sessions() as session:
            rows = await session.scalars(select(ShipmentRow).order_by(ShipmentRow.tracking_id))
            return [_to_shipment(row) for row in rows]

    async def shipment(self, tracking_id: str) -> Shipment | None:
        async with self._sessions() as session:
            row = await session.get(ShipmentRow, tracking_id)
            return None if row is None else _to_shipment(row)

    async def order_dates(self) -> dict[str, datetime]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(OrderRow.order_id, OrderRow.placed_at).where(OrderRow.placed_at.is_not(None))
            )
            return {row.order_id: row.placed_at for row in rows}

    async def save_shipment(self, shipment: Shipment) -> bool:
        values = shipment.model_dump()
        columns = [key for key in values if key != "tracking_id"]
        inserting = pg_insert(ShipmentRow).values(values)
        statement = inserting.on_conflict_do_update(
            index_elements=[ShipmentRow.tracking_id],
            set_={column: inserting.excluded[column] for column in columns},
            where=or_(*(getattr(ShipmentRow, c).is_distinct_from(inserting.excluded[c]) for c in columns)),
        ).returning(ShipmentRow.tracking_id)
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).first() is not None

    async def open_ticket(self, ticket: Ticket) -> bool:
        statement = (
            pg_insert(TicketRow)
            .values(_ticket_row(ticket))
            .on_conflict_do_nothing(index_elements=[TicketRow.ticket_id])
            .returning(TicketRow.ticket_id)
        )
        async with self._sessions.begin() as session:
            if (await session.execute(statement)).first() is None:
                return False
            await _insert(session, TicketMessageRow, _message_rows(ticket))
        return True

    async def add_message(self, ticket_id: str, position: int, message: TicketMessage) -> bool:
        statement = (
            pg_insert(TicketMessageRow)
            .values({"ticket_id": ticket_id, "position": position, **message.model_dump()})
            .on_conflict_do_nothing(index_elements=[TicketMessageRow.ticket_id, TicketMessageRow.position])
            .returning(TicketMessageRow.id)
        )
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).first() is not None

    async def set_status(
        self, ticket_id: str, status: TicketStatus, *, resolved_at: datetime | None = None, csat: int | None = None
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if resolved_at is not None:
            values["resolved_at"] = resolved_at
        if csat is not None:
            values["csat"] = csat
        async with self._sessions.begin() as session:
            await session.execute(update(TicketRow).where(TicketRow.ticket_id == ticket_id).values(values))

    async def ticket(self, ticket_id: str) -> Ticket | None:
        async with self._sessions() as session:
            row = await session.get(TicketRow, ticket_id)
            if row is None:
                return None
            messages = await session.scalars(
                select(TicketMessageRow)
                .where(TicketMessageRow.ticket_id == ticket_id)
                .order_by(TicketMessageRow.position)
            )
            return Ticket.model_validate(
                {
                    **{column: getattr(row, column) for column in _TICKET_COLUMNS},
                    "messages": [
                        TicketMessage.model_validate({"author": m.author, "body": m.body, "created_at": m.created_at})
                        for m in messages
                    ],
                }
            )

    async def kpis(self, metric: KpiMetric, dimension: KpiDimension, *, days: int) -> list[KpiPoint]:
        match = (KpiDailyRow.metric == metric, KpiDailyRow.dimension == dimension)
        async with self._sessions() as session:
            latest = await session.scalar(select(func.max(KpiDailyRow.day)).where(*match))
            if latest is None:
                return []
            rows = await session.scalars(
                select(KpiDailyRow)
                .where(*match, KpiDailyRow.day > latest - timedelta(days=days))
                .order_by(KpiDailyRow.day, KpiDailyRow.key)
            )
            return [KpiPoint.model_validate(row, from_attributes=True) for row in rows]

    async def tickets_opened(self, since: datetime, until: datetime) -> list[Ticket]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(TicketRow)
                .where(TicketRow.created_at > since, TicketRow.created_at <= until)
                .order_by(TicketRow.created_at, TicketRow.ticket_id)
            )
            return [Ticket.model_validate({column: getattr(row, column) for column in _TICKET_COLUMNS}) for row in rows]

    async def texts_to_embed(self, target: EmbeddingTarget, limit: int) -> list[tuple[str, str]]:
        async with self._sessions() as session:
            if target == "reviews":
                rows = await session.execute(
                    select(ReviewRow.review_id, ReviewRow.title, ReviewRow.body)
                    .where(ReviewRow.embedding.is_(None))
                    .order_by(ReviewRow.review_id)
                    .limit(limit)
                )
                return [(row.review_id, f"{row.title}\n{row.body}") for row in rows]
            rows = await session.execute(
                select(TicketMessageRow.ticket_id, TicketMessageRow.position, TicketMessageRow.body)
                .where(TicketMessageRow.embedding.is_(None))
                .order_by(TicketMessageRow.id)
                .limit(limit)
            )
            return [(f"{row.ticket_id}:{row.position}", row.body) for row in rows]

    async def save_embeddings(self, target: EmbeddingTarget, vectors: Mapping[str, Sequence[float]]) -> None:
        if not vectors:
            return
        async with self._sessions.begin() as session:
            if target == "reviews":
                await session.execute(
                    update(ReviewRow),
                    [{"review_id": key, "embedding": list(vector)} for key, vector in vectors.items()],
                )
                return
            for key, vector in vectors.items():
                ticket_id, position = key.rsplit(":", 1)
                await session.execute(
                    update(TicketMessageRow)
                    .where(TicketMessageRow.ticket_id == ticket_id, TicketMessageRow.position == int(position))
                    .values(embedding=list(vector))
                )


_TICKET_COLUMNS = (
    "ticket_id",
    "user_id",
    "order_id",
    "product_id",
    "intent",
    "subject",
    "status",
    "source",
    "created_at",
    "resolved_at",
    "csat",
)


async def _insert(session: AsyncSession, model: type[Any], rows: list[dict[str, Any]]) -> None:
    if rows:
        await session.execute(insert(model), rows)


def _ticket_row(ticket: Ticket) -> dict[str, Any]:
    return ticket.model_dump(exclude={"messages"})


def _message_rows(ticket: Ticket) -> list[dict[str, Any]]:
    return [
        {"ticket_id": ticket.ticket_id, "position": position, **message.model_dump()}
        for position, message in enumerate(ticket.messages)
    ]


def _to_shipment(row: ShipmentRow) -> Shipment:
    return Shipment.model_validate({column.key: getattr(row, column.key) for column in ShipmentRow.__table__.columns})

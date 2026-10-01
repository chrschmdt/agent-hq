from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ahq.db.models.base import Base

EMBEDDING_DIMENSIONS = 1024


def _hnsw(table: str) -> Index:
    return Index(
        f"ix_{table}_embedding_hnsw",
        "embedding",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


class ShipmentRow(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint("status IN ('label_created', 'in_transit', 'delivered', 'cancelled')", name="status"),
        Index(None, "order_id"),
        Index(None, "carrier", "shipped_at"),
        Index(None, "region", "shipped_at"),
        Index(None, "status"),
        {"schema": "retail"},
    )

    tracking_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("retail.orders.order_id"), nullable=False)
    carrier: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefundRow(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        Index(None, "order_id"),
        Index(None, "created_at"),
        {"schema": "retail"},
    )

    refund_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("retail.orders.order_id"), nullable=False)
    amount: Mapped[float] = mapped_column(Double, nullable=False)
    payment_method_id: Mapped[str] = mapped_column(ForeignKey("retail.payment_methods.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRow(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),
        Index(None, "product_id", "created_at"),
        Index(None, "item_id"),
        _hnsw("reviews"),
        {"schema": "retail"},
    )

    review_id: Mapped[str] = mapped_column(Text, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("retail.products.product_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("retail.product_variants.item_id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("retail.customers.user_id"), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class TicketRow(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'waiting_customer', 'resolved', 'escalated')", name="status"),
        CheckConstraint("source IN ('history', 'simulation', 'operator')", name="source"),
        CheckConstraint("csat BETWEEN 1 AND 5", name="csat"),
        Index(None, "user_id"),
        Index(None, "product_id"),
        Index(None, "created_at"),
        Index(None, "status"),
        {"schema": "support"},
    )

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("retail.customers.user_id"))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("retail.orders.order_id"))
    product_id: Mapped[str | None] = mapped_column(ForeignKey("retail.products.product_id"))
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csat: Mapped[int | None] = mapped_column(SmallInteger)


class TicketMessageRow(Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (
        CheckConstraint("author IN ('customer', 'agent', 'system')", name="author"),
        UniqueConstraint("ticket_id", "position"),
        Index(None, "created_at"),
        _hnsw("ticket_messages"),
        {"schema": "support"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("support.tickets.ticket_id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class KpiDailyRow(Base):
    __tablename__ = "daily"
    __table_args__ = (
        CheckConstraint("dimension IN ('store', 'category', 'carrier', 'region')", name="dimension"),
        Index(None, "metric", "dimension", "key", "day"),
        {"schema": "kpi"},
    )

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    dimension: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False)

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, Field

from ahq.domain.base import StrictModel

ShipmentStatus = Literal["label_created", "in_transit", "delivered", "cancelled"]
TicketStatus = Literal["open", "waiting_customer", "resolved", "escalated"]
TicketSource = Literal["history", "simulation", "operator"]
MessageAuthor = Literal["customer", "agent", "system"]
KpiDimension = Literal["store", "category", "carrier", "region"]
KpiMetric = Literal[
    "orders",
    "deliveries",
    "late_delivery_rate",
    "delivery_delay_hours",
    "refund_rate",
    "tickets",
    "resolution_minutes",
    "csat",
]


class Shipment(StrictModel):
    tracking_id: str
    order_id: str
    carrier: str
    state: str
    region: str
    status: ShipmentStatus
    shipped_at: AwareDatetime | None = None
    promised_at: AwareDatetime | None = None
    delivered_at: AwareDatetime | None = None


class Refund(StrictModel):
    refund_id: str
    order_id: str
    amount: float
    payment_method_id: str
    reason: str
    created_at: AwareDatetime


class Review(StrictModel):
    review_id: str
    product_id: str
    item_id: str
    user_id: str
    rating: int = Field(ge=1, le=5)
    title: str
    body: str
    created_at: AwareDatetime


class TicketMessage(StrictModel):
    author: MessageAuthor
    body: str
    created_at: AwareDatetime


class Ticket(StrictModel):
    ticket_id: str
    user_id: str | None
    order_id: str | None = None
    product_id: str | None = None
    intent: str
    subject: str
    status: TicketStatus
    source: TicketSource
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    csat: int | None = Field(default=None, ge=1, le=5)
    messages: tuple[TicketMessage, ...] = ()


class KpiPoint(StrictModel):
    day: date
    metric: KpiMetric
    dimension: KpiDimension
    key: str
    value: float
    samples: int = Field(ge=0)


class WorldHistory(StrictModel):
    placed_at: dict[str, AwareDatetime]
    shipments: tuple[Shipment, ...]
    refunds: tuple[Refund, ...]
    reviews: tuple[Review, ...] = ()
    tickets: tuple[Ticket, ...] = ()
    kpis: tuple[KpiPoint, ...] = ()

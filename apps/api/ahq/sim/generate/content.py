from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import Field

from ahq.domain import StrictModel
from ahq.domain.world import MessageAuthor, Review, Ticket, TicketMessage, TicketStatus


class ReviewRecord(StrictModel):
    review_id: str
    product_id: str
    item_id: str
    user_id: str
    rating: int = Field(ge=1, le=5)
    title: str
    body: str
    days_before_anchor: float = Field(gt=0)

    def to_review(self, anchor: datetime) -> Review:
        return Review(
            **self.model_dump(exclude={"days_before_anchor"}),
            created_at=_minute(anchor - timedelta(days=self.days_before_anchor)),
        )


class TicketMessageRecord(StrictModel):
    author: MessageAuthor
    body: str
    minutes_after_open: float = Field(ge=0)


class TicketRecord(StrictModel):
    ticket_id: str
    user_id: str | None
    order_id: str | None = None
    product_id: str | None = None
    intent: str
    subject: str
    status: TicketStatus
    csat: int | None = Field(default=None, ge=1, le=5)
    days_before_anchor: float = Field(gt=0)
    resolution_minutes: float | None = Field(default=None, ge=0)
    messages: tuple[TicketMessageRecord, ...]

    def to_ticket(self, anchor: datetime) -> Ticket:
        opened = _minute(anchor - timedelta(days=self.days_before_anchor))
        resolved = None if self.resolution_minutes is None else opened + timedelta(minutes=self.resolution_minutes)
        return Ticket(
            ticket_id=self.ticket_id,
            user_id=self.user_id,
            order_id=self.order_id,
            product_id=self.product_id,
            intent=self.intent,
            subject=self.subject,
            status=self.status,
            source="history",
            created_at=opened,
            resolved_at=resolved,
            csat=self.csat,
            messages=tuple(
                TicketMessage(
                    author=message.author,
                    body=message.body,
                    created_at=opened + timedelta(minutes=message.minutes_after_open),
                )
                for message in self.messages
            ),
        )


def load_reviews(path: Path, anchor: datetime) -> tuple[Review, ...]:
    return tuple(ReviewRecord.model_validate_json(line).to_review(anchor) for line in _lines(path))


def load_tickets(path: Path, anchor: datetime) -> tuple[Ticket, ...]:
    return tuple(TicketRecord.model_validate_json(line).to_ticket(anchor) for line in _lines(path))


def _lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if line.strip():
            yield line


def _minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)

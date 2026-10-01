from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from ahq.domain import StrictModel


class KpiRow(StrictModel):
    day: date
    key: str
    value: float
    samples: int


class SimilarTicket(StrictModel):
    ticket_id: str
    subject: str
    intent: str
    status: str
    created_at: datetime
    opening: str
    similarity: float


class TicketCluster(StrictModel):
    size: int
    ticket_ids: list[str]
    examples: list[str] = Field(description="Subjects of the tickets closest to the cluster's centre.")


class Anomaly(StrictModel):
    value: float
    baseline: float
    spread: float
    z_score: float
    ratio: float

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ahq.domain import StrictModel

Category = Literal["quality", "outcome", "efficiency", "safety"]
Direction = Literal["higher", "lower"]
Unit = Literal["rate", "usd", "seconds", "tokens", "count"]


class MetricDef(StrictModel):
    key: str
    label: str
    category: Category
    direction: Direction
    unit: Unit
    min_samples: int = Field(default=5, ge=1)


class Metric(StrictModel):
    key: str
    value: float | None
    samples: int = Field(ge=0)
    successes: int | None = None


class CriterionScore(StrictModel):
    criterion_id: str
    reviewed: int
    passed: int
    failed: int
    raw_pass_rate: float | None
    corrected_pass_rate: float | None
    calibrated: bool
    safety: bool


class Scorecard(StrictModel):
    agent: str
    version_id: str
    runs: int = Field(description="Finished runs counted.")
    metrics: dict[str, Metric]
    criteria: list[CriterionScore]

    def value(self, key: str) -> float | None:
        metric = self.metrics.get(key)
        return None if metric is None else metric.value


class TrendPoint(StrictModel):
    through: int = Field(description="How many of the version's runs had finished by the end of the window.")
    until: datetime = Field(description="When the window's last run finished.")
    scorecard: Scorecard


Action = Literal["continue", "promote", "rollback"]


class CanaryDecision(StrictModel):
    action: Action
    reasons: list[str]


class GateVerdict(StrictModel):
    passed: bool
    reasons: list[str]


class TeamValue(StrictModel):
    tickets: int
    resolved: int
    with_people: int
    open: int
    deflection_rate: float | None
    ticket_cost_usd: float
    cost_per_resolved_usd: float | None
    human_cost_per_ticket_usd: float
    human_cost_usd: float = Field(description="What people would have cost for the tickets the agents resolved.")
    net_savings_usd: float
    median_minutes_to_resolve: float | None
    approvals_per_100: float | None
    incidents: int
    delayed_customers: int
    reached_first: int

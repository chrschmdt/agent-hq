from __future__ import annotations

import secrets
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue

from ahq.domain.base import StrictModel

EvalStatus = Literal["queued", "running", "passed", "failed", "error"]
EvalBackend = Literal["inprocess", "github", "cli"]
Suite = Literal["tau3", "dispatcher", "scenario"]
ProfileChoice = Literal["mock", "low", "medium", "high"]


def new_eval_run_id() -> str:
    return f"ev_{secrets.token_hex(8)}"


class GateParams(StrictModel):
    suite: Suite
    profile: ProfileChoice = "low"
    cases: int = Field(default=3, ge=1, le=200, description="τ³ tasks, routing cases, or scenario days.")
    trials: int = Field(default=1, ge=1, le=8)
    max_usd: float = Field(default=0.5, gt=0, le=20)


class VersionScore(StrictModel):
    version_id: str
    metric: str
    score: float
    cases: int
    passed: int
    cost_usd: float
    details: dict[str, JsonValue] = Field(default_factory=dict)


class GateSummary(StrictModel):
    candidate: VersionScore
    baseline: VersionScore
    passed: bool
    reasons: list[str]


class EvalRun(StrictModel):
    eval_run_id: str
    agent: str
    candidate_id: str
    baseline_id: str
    params: GateParams
    status: EvalStatus
    backend: EvalBackend
    requested_by: str
    created_at: AwareDatetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    url: str | None = Field(default=None, description="Where the run's log can be read, such as a workflow run.")
    summary: GateSummary | None = None
    error: str | None = None
    cost_usd: float = Field(default=0.0, ge=0)


class EvalCase(StrictModel):
    version_id: str
    case_id: str
    trial: int = Field(ge=0)
    passed: bool
    score: float
    cost_usd: float = Field(ge=0)
    seconds: float = Field(ge=0)
    detail: dict[str, JsonValue] = Field(default_factory=dict)

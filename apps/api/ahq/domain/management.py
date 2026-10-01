from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue

from ahq.domain.base import StrictModel
from ahq.domain.evals import ProfileChoice


class VersionStatus(StrEnum):
    DRAFT = "draft"
    EVALUATED = "evaluated"
    CANARY = "canary"
    LIVE = "live"
    RETIRED = "retired"


class VersionConfig(StrictModel):
    model: str | None = Field(
        default=None,
        description="Catalog key of the model this version runs on, or null for the model the profile gives its role.",
    )
    prompt_stable: str
    prompt_context: str
    tools: list[str]
    max_model_calls: int = Field(gt=0)
    max_usd: float = Field(gt=0)

    @property
    def digest(self) -> str:
        text = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()


def version_id_for(agent: str, number: int) -> str:
    return f"{agent}@{number}"


class AgentVersion(StrictModel):
    version_id: str
    agent: str
    number: int = Field(ge=1)
    status: VersionStatus
    config: VersionConfig
    digest: str
    parent_id: str | None = None
    note: str = ""
    created_by: str
    created_at: AwareDatetime
    status_at: AwareDatetime
    status_reason: str | None = None
    canary_pct: int | None = Field(default=None, ge=1, le=100)
    eval_summary: dict[str, JsonValue] | None = None


class Serving(StrictModel):
    live: AgentVersion | None = None
    canary: AgentVersion | None = None


RunOutcome = Literal["waiting_customer", "resolved", "done", "routed", "handed_off", "escalated", "failed"]
FINISHED_OUTCOMES: frozenset[RunOutcome] = frozenset(
    {"resolved", "done", "routed", "handed_off", "escalated", "failed"}
)


class AgentRun(StrictModel):
    work_item_id: str
    agent: str
    version_id: str
    kind: str
    outcome: RunOutcome
    turns: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_tokens: int = Field(default=0, ge=0, description="Input tokens read from the provider's prompt cache.")
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    seconds: float = Field(ge=0)
    approvals: int = Field(default=0, ge=0)
    rejected_approvals: int = Field(default=0, ge=0)
    stop_reason: str | None = None
    error: str | None = None
    started_at: AwareDatetime
    updated_at: AwareDatetime

    @property
    def finished(self) -> bool:
        return self.outcome in FINISHED_OUTCOMES


class AgentControl(StrictModel):
    agent: str
    paused: bool
    reason: str | None = None
    changed_by: str
    changed_at: AwareDatetime


class ModelChoice(StrictModel):
    profile: ProfileChoice
    changed_by: str
    changed_at: AwareDatetime


class ActivityReport(StrictModel):
    records: dict[str, int]
    versions: bool
    passages: int | None
    cleared_by: str
    cleared_at: AwareDatetime


class SpendLine(StrictModel):
    day: date
    agent: str
    model: str
    calls: int = Field(ge=0)
    errors: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class ModelHealth(StrictModel):
    model: str
    consecutive_errors: int = Field(ge=0)
    open_until: datetime | None = None
    last_error: str | None = None
    updated_at: AwareDatetime

    def is_open(self, now: datetime) -> bool:
        return self.open_until is not None and self.open_until > now


CallVerdict = Literal["proceed", "fallback", "pause", "deny"]


class CallDecision(StrictModel):
    verdict: CallVerdict
    model: str
    reason: str | None = None

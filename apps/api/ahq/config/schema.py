from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ahq.domain.base import StrictModel

ModelRoute = Literal["openrouter-anthropic", "openrouter-openai", "fake"]
ModelRole = Literal["smoke", "dispatcher", "support", "ops", "insights", "qa", "guard", "customer", "writer"]
ProfileName = Literal["mock", "low", "medium", "high"]


class ModelSpec(StrictModel):
    route: ModelRoute
    id: str
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float = Field(default=0.0, ge=0)
    cache_write: float = Field(default=0.0, ge=0)
    min_cacheable_tokens: int | None = None
    providers: tuple[str, ...] = ()
    fallback: str | None = None
    reasoning: Literal["adaptive"] | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    reply_format: Literal["schema", "prompt", "tool"] = "schema"
    max_output_tokens: int = Field(default=4096, gt=0)


class EmbeddingSpec(StrictModel):
    id: str
    dimensions: int = Field(gt=0)
    price: float = Field(ge=0)


class RerankSpec(StrictModel):
    id: str
    price: float = Field(ge=0)


class ModelCatalog(StrictModel):
    models: dict[str, ModelSpec]
    embeddings: EmbeddingSpec
    rerank: RerankSpec
    profiles: dict[ProfileName, dict[ModelRole, str]]
    version_models: tuple[ProfileName, ...] = ()
    forced: dict[ModelRole, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _profiles_reference_known_models(self) -> ModelCatalog:
        for profile, roles in self.profiles.items():
            missing_roles = set(ModelRole.__args__) - set(roles)
            if missing_roles:
                raise ValueError(f"profile {profile!r} is missing roles: {sorted(missing_roles)}")
            unknown = {key for key in roles.values() if key not in self.models}
            if unknown:
                raise ValueError(f"profile {profile!r} references unknown models: {sorted(unknown)}")
        fallbacks = {spec.fallback for spec in self.models.values() if spec.fallback is not None}
        if fallbacks - self.models.keys():
            raise ValueError(f"unknown fallback models: {sorted(fallbacks - self.models.keys())}")
        if set(self.forced.values()) - self.models.keys():
            raise ValueError(f"unknown forced models: {sorted(set(self.forced.values()) - self.models.keys())}")
        return self

    def forcing(self, roles: Mapping[ModelRole, str]) -> ModelCatalog:
        return ModelCatalog.model_validate({**self.model_dump(), "forced": {**self.forced, **roles}})

    def resolve(self, profile: ProfileName, role: ModelRole, preferred: str | None = None) -> tuple[str, ModelSpec]:
        if role in self.forced:
            return self.forced[role], self.models[self.forced[role]]
        key = self.profiles[profile][role]
        if preferred is not None and profile in self.version_models:
            if preferred not in self.models:
                raise ValueError(f"unknown model {preferred!r}")
            key = preferred
        return key, self.models[key]


class ClockSpec(StrictModel):
    anchor: AwareDatetime
    timezone: str
    history_days: int = Field(gt=0)

    def day_at(self, moment: datetime) -> date:
        return moment.astimezone(ZoneInfo(self.timezone)).date()


class CarrierSpec(StrictModel):
    id: str
    name: str
    share: float = Field(gt=0, le=1)
    transit_days: tuple[int, int]
    on_time_rate: float = Field(gt=0, le=1)


class WorldConfig(StrictModel):
    clock: ClockSpec
    carriers: tuple[CarrierSpec, ...]
    regions: dict[str, tuple[str, ...]]
    categories: dict[str, tuple[str, ...]]

    @model_validator(mode="after")
    def _consistent(self) -> WorldConfig:
        if not math.isclose(sum(carrier.share for carrier in self.carriers), 1.0):
            raise ValueError("carrier shares must add up to 1")
        for name, groups in (("state", self.regions), ("product", self.categories)):
            members = [member for group in groups.values() for member in group]
            if len(members) != len(set(members)):
                raise ValueError(f"a {name} appears in more than one group")
        return self

    @property
    def anchor(self) -> datetime:
        return self.clock.anchor

    def region_of(self, state: str) -> str:
        return next(region for region, states in self.regions.items() if state in states)

    def category_of(self, product_name: str) -> str:
        return next(category for category, names in self.categories.items() if product_name in names)


RetrievalModeName = Literal["dense", "bm25", "hybrid", "hybrid_rerank"]


class RetrievalConfig(StrictModel):
    mode: RetrievalModeName
    prefetch: int = Field(gt=0)
    rerank_candidates: int = Field(gt=0)
    k: int = Field(gt=0)
    rrf_k: int = Field(gt=0)


class ApprovalPolicy(StrictModel):
    refund_limit_usd: float = Field(ge=0)


class ModelBreaker(StrictModel):
    errors: int = Field(gt=0)
    cooldown_minutes: float = Field(gt=0)


class AgentBreaker(StrictModel):
    failures: int = Field(gt=0)
    window_minutes: float = Field(gt=0)


class DailyBudget(StrictModel):
    total_usd: float = Field(gt=0)
    agents: dict[str, float] = Field(default_factory=dict)


class CallPolicy(StrictModel):
    slots: dict[str, int]
    default_slots: int = Field(gt=0)
    lease_seconds: float = Field(gt=0)
    wait_seconds: float = Field(ge=0)
    attempts: int = Field(ge=1)
    backoff_seconds: float = Field(gt=0)
    max_wait_seconds: float = Field(gt=0)

    def slots_for(self, provider: str) -> int:
        return self.slots.get(provider, self.default_slots)


class BudgetConfig(StrictModel):
    daily: DailyBudget
    model_breaker: ModelBreaker
    agent_breaker: AgentBreaker
    calls: CallPolicy


class RollbackThresholds(StrictModel):
    escalation_increase: float = Field(gt=0)
    error_increase: float = Field(gt=0)
    rejection_increase: float = Field(gt=0)
    cost_ratio: float = Field(gt=1)
    qa_drop: float = Field(gt=0)
    escalation_ceiling: float = Field(gt=0, le=1)
    error_ceiling: float = Field(gt=0, le=1)


class GateSuite(StrictModel):
    suite: Literal["tau3", "dispatcher", "scenario"]
    cases: int = Field(gt=0)
    trials: int = Field(gt=0)


class GatePolicy(StrictModel):
    score_drop: float = Field(ge=0)
    cost_ratio: float = Field(gt=1)
    suites: dict[str, GateSuite]


class CanaryConfig(StrictModel):
    default_pct: int = Field(ge=1, le=100)
    min_runs: int = Field(gt=0)
    promote_after: int = Field(gt=0)
    auto_promote: bool
    baseline_runs: int = Field(gt=0)
    rollback: RollbackThresholds
    gate: GatePolicy


class CalibrationPolicy(StrictModel):
    min_positive: int = Field(gt=0)
    min_negative: int = Field(gt=0)
    min_tpr: float = Field(gt=0, le=1)
    min_tnr: float = Field(gt=0, le=1)
    window: int = Field(gt=1)


class InputCheckConfig(StrictModel):
    classifier: bool
    patterns: list[str]

    @field_validator("patterns")
    @classmethod
    def _compiles(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            re.compile(pattern)
        return patterns


class ReplyCheckConfig(StrictModel):
    allowed_hosts: list[str]


class GuardConfig(StrictModel):
    input: InputCheckConfig
    output: ReplyCheckConfig


class RoiConfig(StrictModel):
    human_cost_per_ticket_usd: float = Field(gt=0)


class QaConfig(StrictModel):
    sample_rate: float = Field(ge=0, le=1)
    escalations: bool
    rejected_approvals: bool
    canary: bool
    calibration: CalibrationPolicy

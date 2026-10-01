from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from ahq.config.schema import (
    AgentBreaker,
    ApprovalPolicy,
    BudgetConfig,
    CalibrationPolicy,
    CallPolicy,
    CanaryConfig,
    CarrierSpec,
    ClockSpec,
    DailyBudget,
    EmbeddingSpec,
    GatePolicy,
    GateSuite,
    GuardConfig,
    InputCheckConfig,
    ModelBreaker,
    ModelCatalog,
    ModelRole,
    ModelRoute,
    ModelSpec,
    ProfileName,
    QaConfig,
    ReplyCheckConfig,
    RerankSpec,
    RetrievalConfig,
    RetrievalModeName,
    RoiConfig,
    RollbackThresholds,
    WorldConfig,
)

CONFIG_DIR = Path(__file__).resolve().parent


def _read(name: str) -> dict[str, object]:
    with (CONFIG_DIR / name).open("rb") as handle:
        return tomllib.load(handle)


@lru_cache(maxsize=1)
def load_model_catalog() -> ModelCatalog:
    return ModelCatalog.model_validate(_read("models.toml"))


@lru_cache(maxsize=1)
def load_retrieval_config() -> RetrievalConfig:
    return RetrievalConfig.model_validate(_read("retrieval.toml"))


@lru_cache(maxsize=1)
def load_approval_policy() -> ApprovalPolicy:
    return ApprovalPolicy.model_validate(_read("approvals.toml"))


@lru_cache(maxsize=1)
def load_budget_config() -> BudgetConfig:
    return BudgetConfig.model_validate(_read("budgets.toml"))


@lru_cache(maxsize=1)
def load_canary_config() -> CanaryConfig:
    return CanaryConfig.model_validate(_read("canary.toml"))


@lru_cache(maxsize=1)
def load_qa_config() -> QaConfig:
    return QaConfig.model_validate(_read("qa.toml"))


@lru_cache(maxsize=1)
def load_guard_config() -> GuardConfig:
    return GuardConfig.model_validate(_read("guardrails.toml"))


@lru_cache(maxsize=1)
def load_roi_config() -> RoiConfig:
    return RoiConfig.model_validate(_read("roi.toml"))


@lru_cache(maxsize=1)
def load_world_config() -> WorldConfig:
    return WorldConfig.model_validate(_read("world.toml"))


__all__ = [
    "CONFIG_DIR",
    "AgentBreaker",
    "ApprovalPolicy",
    "BudgetConfig",
    "CalibrationPolicy",
    "CallPolicy",
    "CanaryConfig",
    "CarrierSpec",
    "ClockSpec",
    "DailyBudget",
    "EmbeddingSpec",
    "GatePolicy",
    "GateSuite",
    "GuardConfig",
    "InputCheckConfig",
    "ModelBreaker",
    "ModelCatalog",
    "ModelRole",
    "ModelRoute",
    "ModelSpec",
    "ProfileName",
    "QaConfig",
    "ReplyCheckConfig",
    "RerankSpec",
    "RetrievalConfig",
    "RetrievalModeName",
    "RoiConfig",
    "RollbackThresholds",
    "WorldConfig",
    "load_approval_policy",
    "load_budget_config",
    "load_canary_config",
    "load_guard_config",
    "load_model_catalog",
    "load_qa_config",
    "load_retrieval_config",
    "load_roi_config",
    "load_world_config",
]

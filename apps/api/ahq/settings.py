from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
TAU3_VERSION = "v1.0.1"

ModelProfile = Literal["mock", "low", "medium", "high"]
QueueBackend = Literal["inprocess", "vercel"]
ToolTransport = Literal["asgi", "http", "direct"]
Environment = Literal["local", "development", "preview", "production"]
AgentVersions = Literal["registry", "code"]
EvalBackend = Literal["inprocess", "github"]


def _alias(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _empty_means_unset(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value != ""}  # pyright: ignore[reportUnknownVariableType]
        return data

    environment: Environment = Field(default="local", validation_alias=_alias("AHQ_ENV", "VERCEL_ENV"))
    model_profile: ModelProfile = Field(default="mock", validation_alias=_alias("AHQ_MODEL_PROFILE"))
    model_roles: dict[str, str] = Field(default_factory=dict, validation_alias=_alias("AHQ_MODEL_ROLES"))
    fake_pace_seconds: float = Field(default=0.0, ge=0, validation_alias=_alias("AHQ_FAKE_PACE"))

    database_url: SecretStr | None = Field(default=None, validation_alias=_alias("DATABASE_URL"))
    database_url_unpooled: SecretStr | None = Field(default=None, validation_alias=_alias("DATABASE_URL_UNPOOLED"))
    test_database_url: SecretStr = Field(
        default=SecretStr("postgresql://ahq:ahq@localhost:5432/ahq_test"),
        validation_alias=_alias("AHQ_TEST_DATABASE_URL"),
    )
    test_pooled_database_url: SecretStr = Field(
        default=SecretStr("postgresql://ahq:ahq@localhost:6432/ahq_test"),
        validation_alias=_alias("AHQ_TEST_POOLED_DATABASE_URL"),
    )

    data_dir: Path = Field(default=REPO_ROOT / "data", validation_alias=_alias("AHQ_DATA_DIR"))
    kb_dir: Path = Field(default=REPO_ROOT / "kb", validation_alias=_alias("AHQ_KB_DIR"))
    seed_memory: bool = Field(default=False, validation_alias=_alias("AHQ_SEED_MEMORY"))
    offline_recording: Path = Field(
        default=REPO_ROOT / "data" / "recordings" / "offline-day.json.gz",
        validation_alias=_alias("AHQ_OFFLINE_RECORDING"),
    )

    qdrant_url: str | None = Field(default=None, validation_alias=_alias("QDRANT_URL"))
    qdrant_api_key: SecretStr | None = Field(default=None, validation_alias=_alias("QDRANT_API_KEY"))

    openrouter_api_key: SecretStr | None = Field(default=None, validation_alias=_alias("OPENROUTER_API_KEY"))
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api", validation_alias=_alias("OPENROUTER_BASE_URL")
    )

    langsmith_api_key: SecretStr | None = Field(default=None, validation_alias=_alias("LANGSMITH_API_KEY"))
    langsmith_project: str = Field(default="ahq", validation_alias=_alias("LANGSMITH_PROJECT"))
    trace_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0, validation_alias=_alias("AHQ_TRACE_SAMPLE_RATE"))

    queue_backend: QueueBackend = Field(default="inprocess", validation_alias=_alias("AHQ_QUEUE_BACKEND"))
    queue_region: str = Field(default="iad1", validation_alias=_alias("AHQ_QUEUE_REGION", "VERCEL_REGION"))
    queue_concurrency: int = Field(default=1, ge=1, le=64, validation_alias=_alias("AHQ_QUEUE_CONCURRENCY"))
    segment_budget_s: float = Field(default=60.0, gt=0, validation_alias=_alias("AHQ_SEGMENT_BUDGET_S"))

    operator_token: SecretStr | None = Field(default=None, validation_alias=_alias("AHQ_OPERATOR_TOKEN"))
    mcp_token_secret: SecretStr | None = Field(default=None, validation_alias=_alias("AHQ_MCP_TOKEN_SECRET"))
    cron_secret: SecretStr | None = Field(default=None, validation_alias=_alias("CRON_SECRET"))

    tool_transport: ToolTransport = Field(default="asgi", validation_alias=_alias("AHQ_TOOL_TRANSPORT"))
    site_url: str | None = Field(default=None, validation_alias=_alias("AHQ_SITE_URL"))
    public_base_url: str = Field(default="http://localhost:8000", validation_alias=_alias("AHQ_PUBLIC_BASE_URL"))
    vercel_url: str | None = Field(default=None, validation_alias=_alias("VERCEL_URL"))
    vercel_branch_url: str | None = Field(default=None, validation_alias=_alias("VERCEL_BRANCH_URL"))
    vercel_production_url: str | None = Field(default=None, validation_alias=_alias("VERCEL_PROJECT_PRODUCTION_URL"))
    vercel_bypass_secret: SecretStr | None = Field(
        default=None, validation_alias=_alias("VERCEL_AUTOMATION_BYPASS_SECRET")
    )

    agent_versions: AgentVersions = Field(default="registry", validation_alias=_alias("AHQ_AGENT_VERSIONS"))

    eval_backend: EvalBackend | None = Field(default=None, validation_alias=_alias("AHQ_EVAL_BACKEND"))
    github_token: SecretStr | None = Field(default=None, validation_alias=_alias("AHQ_GITHUB_TOKEN"))
    github_repo: str | None = Field(default=None, validation_alias=_alias("AHQ_GITHUB_REPO"))
    github_ref: str = Field(default="master", validation_alias=_alias("AHQ_GITHUB_REF"))

    sse_max_seconds: float = Field(default=240.0, gt=0, validation_alias=_alias("AHQ_SSE_MAX_SECONDS"))
    sse_poll_seconds: float = Field(default=0.75, gt=0, validation_alias=_alias("AHQ_SSE_POLL_SECONDS"))
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0, validation_alias=_alias("AHQ_SSE_HEARTBEAT_SECONDS"))

    @property
    def self_url(self) -> str:
        if self.environment == "production" and self.site_url:
            return self.site_url.rstrip("/")
        if self.environment == "production" and self.vercel_production_url:
            return f"https://{self.vercel_production_url}"
        if self.vercel_url:
            return f"https://{self.vercel_url}"
        return self.public_base_url

    @property
    def self_headers(self) -> dict[str, str]:
        if self.vercel_bypass_secret is None:
            return {}
        return {"x-vercel-protection-bypass": self.vercel_bypass_secret.get_secret_value()}

    @property
    def context_key(self) -> str:
        if self.mcp_token_secret is None and self.is_deployed:
            raise RuntimeError("AHQ_MCP_TOKEN_SECRET must be set on deployed environments")
        secret = self.mcp_token_secret.get_secret_value() if self.mcp_token_secret is not None else "local"
        return hmac.new(secret.encode(), b"call-context", hashlib.sha256).hexdigest()

    @property
    def evals_run_on(self) -> EvalBackend:
        if self.eval_backend is not None:
            return self.eval_backend
        return "github" if self.github_token is not None else "inprocess"

    @property
    def is_vercel(self) -> bool:
        return self.vercel_url is not None

    @property
    def is_deployed(self) -> bool:
        return self.is_vercel or self.environment in {"preview", "production"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

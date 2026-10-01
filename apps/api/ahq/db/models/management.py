from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ahq.db.models.base import Base

SCHEMA = "agents"
VERSION_STATUSES = "status IN ('draft', 'evaluated', 'canary', 'live', 'retired')"


class AgentVersionRow(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent", "number"),
        UniqueConstraint("agent", "digest"),
        CheckConstraint(VERSION_STATUSES, name="status"),
        Index("ix_agent_versions_one_live", "agent", unique=True, postgresql_where=text("status = 'live'")),
        Index("ix_agent_versions_one_canary", "agent", unique=True, postgresql_where=text("status = 'canary'")),
        {"schema": SCHEMA},
    )

    version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text)
    canary_pct: Mapped[int | None] = mapped_column(Integer)
    eval_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index(None, "version_id", "updated_at"),
        Index(None, "agent", "updated_at"),
        {"schema": SCHEMA},
    )

    work_item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agent: Mapped[str] = mapped_column(Text, primary_key=True)
    version_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    finished: Mapped[bool] = mapped_column(Boolean, nullable=False)
    turns: Mapped[int] = mapped_column(Integer, nullable=False)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Double, nullable=False)
    seconds: Mapped[float] = mapped_column(Double, nullable=False)
    approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentControlRow(Base):
    __tablename__ = "agent_controls"
    __table_args__ = ({"schema": SCHEMA},)

    agent: Mapped[str] = mapped_column(Text, primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpendDailyRow(Base):
    __tablename__ = "spend_daily"
    __table_args__ = ({"schema": SCHEMA},)

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    agent: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Double, nullable=False)


class ModelHealthRow(Base):
    __tablename__ = "model_health"
    __table_args__ = ({"schema": SCHEMA},)

    model: Mapped[str] = mapped_column(Text, primary_key=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, nullable=False)
    open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderSlotRow(Base):
    __tablename__ = "provider_slots"
    __table_args__ = ({"schema": SCHEMA},)

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    holder: Mapped[str | None] = mapped_column(Text)
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QaReviewRow(Base):
    __tablename__ = "qa_reviews"
    __table_args__ = (
        UniqueConstraint("work_item_id", "agent"),
        Index(None, "version_id", "created_at"),
        Index(None, "agent", "created_at"),
        {"schema": SCHEMA},
    )

    review_id: Mapped[str] = mapped_column(Text, primary_key=True)
    work_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    version_id: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[str] = mapped_column(Text, nullable=False)
    judge_model: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Double, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QaLabelRow(Base):
    __tablename__ = "qa_labels"
    __table_args__ = (CheckConstraint("verdict IN ('pass', 'fail')", name="verdict"), {"schema": SCHEMA})

    work_item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agent: Mapped[str] = mapped_column(Text, primary_key=True)
    criterion_id: Mapped[str] = mapped_column(Text, primary_key=True)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    labeled_by: Mapped[str] = mapped_column(Text, nullable=False)
    labeled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvalRunRow(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'passed', 'failed', 'error')", name="status"),
        Index(None, "agent", "created_at"),
        {"schema": SCHEMA},
    )

    eval_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_id: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_id: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    backend: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Double, nullable=False)


class EvalCaseRow(Base):
    __tablename__ = "eval_cases"
    __table_args__ = ({"schema": SCHEMA},)

    eval_run_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{SCHEMA}.eval_runs.eval_run_id", ondelete="CASCADE"), primary_key=True
    )
    version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    trial: Mapped[int] = mapped_column(Integer, primary_key=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float] = mapped_column(Double, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Double, nullable=False)
    seconds: Mapped[float] = mapped_column(Double, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

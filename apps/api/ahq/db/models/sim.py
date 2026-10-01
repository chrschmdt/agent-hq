from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Double, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ahq.db.models.base import Base


class SimRunRow(Base):
    __tablename__ = "sim_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'paused', 'finished', 'stopped')", name="status"),
        Index(None, "created_at"),
        {"schema": "ops"},
    )

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sim_now: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tick_no: Mapped[int] = mapped_column(Integer, nullable=False)
    tick_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    tick_seconds: Mapped[float] = mapped_column(Double, nullable=False)
    agent_tickets: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    alerts_to_agents: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SimScriptRow(Base):
    __tablename__ = "sim_script"
    __table_args__ = (
        Index(None, "run_id", "due_at"),
        {"schema": "ops"},
    )

    run_id: Mapped[str] = mapped_column(ForeignKey("ops.sim_runs.run_id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

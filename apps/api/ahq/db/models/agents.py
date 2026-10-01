from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ahq.db.models.base import Base

SCHEMA = "agents"


class ToolCallAuditRow(Base):
    __tablename__ = "tool_calls_audit"
    __table_args__ = (
        Index(None, "work_item_id", "recorded_at"),
        Index(None, "approval_id"),
        {"schema": SCHEMA},
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    work_item_id: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    approval_id: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

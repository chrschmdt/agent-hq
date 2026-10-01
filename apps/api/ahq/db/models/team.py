from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ahq.db.models.base import Base

SCHEMA = "agents"


class IncidentRow(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index(None, "created_at"), {"schema": SCHEMA})

    incident_id: Mapped[str] = mapped_column(Text, primary_key=True)
    work_item_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KbDraftRow(Base):
    __tablename__ = "kb_drafts"
    __table_args__ = (Index(None, "status"), {"schema": SCHEMA})

    draft_id: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProposalRow(Base):
    __tablename__ = "proposals"
    __table_args__ = (Index(None, "status", "created_at"), {"schema": SCHEMA})

    proposal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    work_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    incident_id: Mapped[str | None] = mapped_column(Text, ForeignKey(f"{SCHEMA}.incidents.incident_id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    draft_id: Mapped[str | None] = mapped_column(Text, ForeignKey(f"{SCHEMA}.kb_drafts.draft_id"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

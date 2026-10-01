from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.db.models import IncidentRow, KbDraftRow, ProposalRow
from ahq.domain import ConflictError, NotFoundError
from ahq.domain.team import Incident, KbDraft, ProposalRecord


class PgTeamRecords:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def file_incident(self, incident: Incident) -> Incident:
        report = incident.report
        values = {
            "incident_id": incident.incident_id,
            "work_item_id": incident.work_item_id,
            "title": report.title,
            "severity": report.severity,
            "status": incident.status,
            "report": report.model_dump(mode="json"),
            "detected_at": incident.detected_at,
            "created_at": incident.created_at,
        }
        async with self._sessions.begin() as session:
            await session.execute(insert(IncidentRow).values(values).on_conflict_do_nothing())
            row = await session.scalar(select(IncidentRow).where(IncidentRow.work_item_id == incident.work_item_id))
        assert row is not None
        return _incident(row)

    async def incident(self, incident_id: str) -> Incident | None:
        async with self._sessions() as session:
            row = await session.get(IncidentRow, incident_id)
        return None if row is None else _incident(row)

    async def incidents(self, limit: int = 50) -> list[Incident]:
        async with self._sessions() as session:
            rows = await session.scalars(select(IncidentRow).order_by(IncidentRow.created_at.desc()).limit(limit))
            return [_incident(row) for row in rows]

    async def add_proposals(self, proposals: Sequence[ProposalRecord]) -> None:
        if not proposals:
            return
        rows = [
            {
                "proposal_id": record.proposal_id,
                "work_item_id": record.work_item_id,
                "incident_id": record.incident_id,
                "kind": record.proposal.kind,
                "title": record.proposal.title,
                "body": record.proposal.model_dump(mode="json"),
                "draft_id": record.proposal.draft_id,
                "status": record.status,
                "created_at": record.created_at,
            }
            for record in proposals
        ]
        async with self._sessions.begin() as session:
            await session.execute(insert(ProposalRow).values(rows).on_conflict_do_nothing())

    async def proposal(self, proposal_id: str) -> ProposalRecord | None:
        async with self._sessions() as session:
            row = await session.get(ProposalRow, proposal_id)
        return None if row is None else _proposal(row)

    async def proposals(self, status: Literal["pending", "approved", "rejected"] | None = None) -> list[ProposalRecord]:
        query = select(ProposalRow).order_by(ProposalRow.created_at.desc(), ProposalRow.proposal_id)
        if status is not None:
            query = query.where(ProposalRow.status == status)
        async with self._sessions() as session:
            return [_proposal(row) for row in await session.scalars(query)]

    async def decide_proposal(
        self, proposal_id: str, status: Literal["approved", "rejected"], *, by: str, note: str | None, at: datetime
    ) -> ProposalRecord:
        async with self._sessions.begin() as session:
            row = await session.scalar(
                update(ProposalRow)
                .where(ProposalRow.proposal_id == proposal_id, ProposalRow.status == "pending")
                .values(status=status, decided_by=by, note=note, decided_at=at)
                .returning(ProposalRow)
            )
            if row is None:
                existing = await session.get(ProposalRow, proposal_id)
                if existing is None:
                    raise NotFoundError(f"proposal {proposal_id} not found")
                raise ConflictError(f"proposal {proposal_id} was already {existing.status}")
            return _proposal(row)

    async def save_draft(self, draft: KbDraft) -> KbDraft:
        values = draft.model_dump()
        async with self._sessions.begin() as session:
            await session.execute(insert(KbDraftRow).values(values).on_conflict_do_nothing())
            row = await session.get(KbDraftRow, draft.draft_id)
        assert row is not None
        return _draft(row)

    async def draft(self, draft_id: str) -> KbDraft | None:
        async with self._sessions() as session:
            row = await session.get(KbDraftRow, draft_id)
        return None if row is None else _draft(row)

    async def drafts(self, status: Literal["pending", "published", "rejected"] | None = None) -> list[KbDraft]:
        query = select(KbDraftRow).order_by(KbDraftRow.created_at, KbDraftRow.draft_id)
        if status is not None:
            query = query.where(KbDraftRow.status == status)
        async with self._sessions() as session:
            return [_draft(row) for row in await session.scalars(query)]

    async def set_draft_status(
        self, draft_id: str, status: Literal["published", "rejected"], *, at: datetime
    ) -> KbDraft:
        values = {"status": status, "published_at": at if status == "published" else None}
        async with self._sessions.begin() as session:
            row = await session.scalar(
                update(KbDraftRow).where(KbDraftRow.draft_id == draft_id).values(values).returning(KbDraftRow)
            )
            if row is None:
                raise NotFoundError(f"draft {draft_id} not found")
            return _draft(row)


def _incident(row: IncidentRow) -> Incident:
    return Incident.model_validate(
        {
            "incident_id": row.incident_id,
            "work_item_id": row.work_item_id,
            "report": row.report,
            "status": row.status,
            "detected_at": row.detected_at,
            "created_at": row.created_at,
        }
    )


def _proposal(row: ProposalRow) -> ProposalRecord:
    return ProposalRecord.model_validate(
        {
            "proposal_id": row.proposal_id,
            "work_item_id": row.work_item_id,
            "incident_id": row.incident_id,
            "proposal": row.body,
            "status": row.status,
            "decided_by": row.decided_by,
            "note": row.note,
            "created_at": row.created_at,
            "decided_at": row.decided_at,
        }
    )


def _draft(row: KbDraftRow) -> KbDraft:
    return KbDraft.model_validate({column: getattr(row, column) for column in KbDraft.model_fields})

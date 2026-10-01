from __future__ import annotations

from typing import Any

from sqlalchemy import Row, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from ahq.db.models import ApprovalRow
from ahq.domain import (
    Approval,
    ApprovalDecision,
    ApprovalId,
    ApprovalRequest,
    ApprovalStatus,
    ConflictError,
    NotFoundError,
    WorkItemId,
    new_approval_id,
)
from ahq.ports import Clock

_COLUMNS = (
    ApprovalRow.id,
    ApprovalRow.work_item_id,
    ApprovalRow.interrupt_id,
    ApprovalRow.status,
    ApprovalRow.request,
    ApprovalRow.decision,
    ApprovalRow.decided_by,
    ApprovalRow.created_at,
    ApprovalRow.decided_at,
)


def _to_approval(row: Row[Any]) -> Approval:
    return Approval(
        id=ApprovalId(row.id),
        work_item_id=WorkItemId(row.work_item_id),
        interrupt_id=row.interrupt_id,
        status=ApprovalStatus(row.status),
        request=ApprovalRequest.model_validate(row.request),
        decision=ApprovalDecision.model_validate(row.decision) if row.decision else None,
        decided_by=row.decided_by,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


class PgApprovalStore:
    def __init__(self, sessions: async_sessionmaker, clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def open(self, work_item_id: WorkItemId, interrupt_id: str, request: ApprovalRequest) -> Approval:
        values = {
            "id": new_approval_id(),
            "work_item_id": work_item_id,
            "interrupt_id": interrupt_id,
            "status": ApprovalStatus.PENDING.value,
            "request": request.model_dump(mode="json"),
            "created_at": self._clock.now(),
        }
        statement = (
            insert(ApprovalRow)
            .values(values)
            .on_conflict_do_nothing(index_elements=[ApprovalRow.work_item_id, ApprovalRow.interrupt_id])
        )
        existing = select(*_COLUMNS).where(
            ApprovalRow.work_item_id == work_item_id, ApprovalRow.interrupt_id == interrupt_id
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)
            row = (await session.execute(existing)).one()
        return _to_approval(row)

    async def get(self, approval_id: ApprovalId) -> Approval:
        async with self._sessions() as session:
            row = (await session.execute(select(*_COLUMNS).where(ApprovalRow.id == approval_id))).one_or_none()
        if row is None:
            raise NotFoundError(f"approval {approval_id} not found")
        return _to_approval(row)

    async def decide(self, approval_id: ApprovalId, decision: ApprovalDecision, decided_by: str) -> Approval:
        query = (
            update(ApprovalRow)
            .where(ApprovalRow.id == approval_id, ApprovalRow.status == ApprovalStatus.PENDING.value)
            .values(
                status=decision.status.value,
                decision=decision.model_dump(mode="json"),
                decided_by=decided_by,
                decided_at=self._clock.now(),
            )
            .returning(*_COLUMNS)
        )
        async with self._sessions.begin() as session:
            row = (await session.execute(query)).one_or_none()
        if row is None:
            await self.get(approval_id)
            raise ConflictError(f"approval {approval_id} was already decided")
        return _to_approval(row)

    async def pending(self) -> list[Approval]:
        query = (
            select(*_COLUMNS).where(ApprovalRow.status == ApprovalStatus.PENDING.value).order_by(ApprovalRow.created_at)
        )
        async with self._sessions() as session:
            return [_to_approval(row) for row in await session.execute(query)]

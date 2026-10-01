from __future__ import annotations

from collections.abc import Collection
from datetime import timedelta
from typing import Protocol

from pydantic import JsonValue

from ahq.domain import (
    Approval,
    ApprovalDecision,
    ApprovalId,
    ApprovalRequest,
    WorkItem,
    WorkItemId,
    WorkKind,
    WorkStatus,
)


class WorkStore(Protocol):
    async def create(self, kind: WorkKind, input: dict[str, JsonValue], *, key: str | None = None) -> WorkItem: ...

    async def get(self, work_item_id: WorkItemId) -> WorkItem: ...

    async def by_key(self, key: str) -> WorkItem | None: ...

    async def list(
        self,
        *,
        statuses: Collection[WorkStatus] | None = None,
        kinds: Collection[WorkKind] | None = None,
        owner: str | None = None,
        limit: int = 100,
    ) -> list[WorkItem]: ...

    async def set_owner(self, work_item_id: WorkItemId, owner: str) -> WorkItem: ...

    async def set_status(
        self, work_item_id: WorkItemId, status: WorkStatus, *, error: str | None = None
    ) -> WorkItem: ...

    async def acquire_lease(self, work_item_id: WorkItemId, owner: str, ttl: timedelta) -> bool: ...

    async def release_lease(self, work_item_id: WorkItemId, owner: str) -> None: ...

    async def count_active(self) -> int: ...


class ApprovalStore(Protocol):
    async def open(self, work_item_id: WorkItemId, interrupt_id: str, request: ApprovalRequest) -> Approval: ...

    async def get(self, approval_id: ApprovalId) -> Approval: ...

    async def decide(self, approval_id: ApprovalId, decision: ApprovalDecision, decided_by: str) -> Approval: ...

    async def pending(self) -> list[Approval]: ...

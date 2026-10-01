from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue

from ahq.domain.base import StrictModel
from ahq.domain.ids import ApprovalId, WorkItemId


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class ApprovalRequest(StrictModel):
    action: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    reason: str
    cost_usd: float | None = None
    evidence: list[str] = Field(default_factory=list)


class ApprovalDecision(StrictModel):
    verdict: Literal["approve", "edit", "reject"]
    arguments: dict[str, JsonValue] | None = None
    note: str | None = None

    @property
    def status(self) -> ApprovalStatus:
        return {
            "approve": ApprovalStatus.APPROVED,
            "edit": ApprovalStatus.EDITED,
            "reject": ApprovalStatus.REJECTED,
        }[self.verdict]


class Approval(StrictModel):
    id: ApprovalId
    work_item_id: WorkItemId
    interrupt_id: str
    status: ApprovalStatus
    request: ApprovalRequest
    decision: ApprovalDecision | None = None
    decided_by: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class ApprovalResume(StrictModel):
    approval_id: ApprovalId
    decision: ApprovalDecision

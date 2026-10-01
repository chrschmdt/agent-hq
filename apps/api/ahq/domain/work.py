from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, JsonValue

from ahq.domain.base import StrictModel
from ahq.domain.ids import ThreadId, WorkItemId


class WorkKind(StrEnum):
    SMOKE = "smoke"
    TICKET = "ticket"
    ALERT = "alert"
    FLAG = "flag"


class WorkStatus(StrEnum):
    NEW = "new"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CUSTOMER = "waiting_customer"
    DONE = "done"
    ESCALATED = "escalated"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {WorkStatus.DONE, WorkStatus.ESCALATED, WorkStatus.FAILED, WorkStatus.CANCELLED}


class WorkItem(StrictModel):
    id: WorkItemId
    kind: WorkKind
    status: WorkStatus
    thread_id: ThreadId
    input: dict[str, JsonValue] = Field(default_factory=dict)
    owner: str | None = None
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

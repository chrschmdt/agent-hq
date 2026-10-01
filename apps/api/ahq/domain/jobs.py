from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import Field

from ahq.domain.base import StrictModel
from ahq.domain.ids import ApprovalId, JobId, WorkItemId, new_job_id
from ahq.domain.quality import ReviewReason


class Topic(StrEnum):
    WORK = "work"
    SIM = "sim"
    CUSTOMER = "customer"
    QA = "qa"
    EVAL = "eval"


class Job(StrictModel):
    topic: ClassVar[Topic]
    job_id: JobId = Field(default_factory=new_job_id)

    @property
    def idempotency_key(self) -> str:
        return self.job_id


class SegmentJob(Job):
    topic: ClassVar[Topic] = Topic.WORK
    action: Literal["start", "resume", "continue", "customer_message"]
    work_item_id: WorkItemId
    approval_id: ApprovalId | None = None
    position: int | None = Field(default=None, ge=0)

    @property
    def idempotency_key(self) -> str:
        if self.action == "start":
            return f"start:{self.work_item_id}"
        if self.action == "customer_message" and self.position is not None:
            return f"message:{self.work_item_id}:{self.position}"
        return self.job_id


class SimTickJob(Job):
    topic: ClassVar[Topic] = Topic.SIM
    run_id: str
    tick_no: int = Field(ge=0)
    resume: str | None = None

    @property
    def idempotency_key(self) -> str:
        suffix = f":{self.resume}" if self.resume else ""
        return f"sim:{self.run_id}:{self.tick_no}{suffix}"


class CustomerTurnJob(Job):
    topic: ClassVar[Topic] = Topic.CUSTOMER
    work_item_id: WorkItemId
    position: int = Field(ge=0)
    rate_only: bool = False

    @property
    def idempotency_key(self) -> str:
        return f"customer:{self.work_item_id}:{self.position}:{'rate' if self.rate_only else 'say'}"


class QaReviewJob(Job):
    topic: ClassVar[Topic] = Topic.QA
    work_item_id: WorkItemId
    agent: str
    version_id: str
    reason: ReviewReason

    @property
    def idempotency_key(self) -> str:
        return f"qa:{self.work_item_id}:{self.agent}"


class EvalJob(Job):
    topic: ClassVar[Topic] = Topic.EVAL
    eval_run_id: str

    @property
    def idempotency_key(self) -> str:
        return f"eval:{self.eval_run_id}"

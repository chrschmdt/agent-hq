from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from ahq.domain.base import StrictModel

Verdict = Literal["pass", "fail", "unknown"]
ReviewReason = Literal["sample", "escalation", "rejected_approval", "canary", "requested"]


class CriterionVerdict(StrictModel):
    """The reviewer's verdict on one rubric criterion, reasoning first."""

    criterion_id: str = Field(description="The id of the rubric criterion, repeated from the rubric.")
    critique: str = Field(description="What the run shows for this criterion, written before deciding.")
    verdict: Verdict = Field(
        description="pass if the run meets the criterion, fail if it does not, unknown if the run never reached it."
    )


class QAReview(StrictModel):
    """How the QA reviewer answers: one verdict per criterion, then a line on the run as a whole."""

    criteria: list[CriterionVerdict]
    summary: str = Field(description="One sentence on the run's quality.")


class ReviewRecord(StrictModel):
    review_id: str
    work_item_id: str
    agent: str
    version_id: str
    rubric: str = Field(description="The rubric and its version, such as `support@1`.")
    judge_model: str
    reason: ReviewReason
    criteria: list[CriterionVerdict]
    summary: str
    cost_usd: float = Field(ge=0)
    created_at: AwareDatetime

    def verdict(self, criterion_id: str) -> Verdict:
        for criterion in self.criteria:
            if criterion.criterion_id == criterion_id:
                return criterion.verdict
        return "unknown"


def review_id_for(work_item_id: str, agent: str) -> str:
    return f"qa_{work_item_id.removeprefix('wi_')}_{agent}"


class QALabel(StrictModel):
    work_item_id: str
    agent: str
    criterion_id: str
    verdict: Literal["pass", "fail"]
    labeled_by: str
    labeled_at: AwareDatetime

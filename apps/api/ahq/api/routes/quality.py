from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import Field

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import (
    ConflictError,
    Event,
    EventKind,
    InvalidRequest,
    NotFoundError,
    QALabel,
    QaReviewJob,
    ReviewRecord,
    StrictModel,
    WorkItemId,
)
from ahq.grading import Criterion, Rubric, RunMaterial, load_rubric, rubric_agents
from ahq.management import CriterionCalibration

router = APIRouter(tags=["quality"])
GUARDRAIL_EVENTS = 500
RECENT_BLOCKS = 12


class Block(StrictModel):
    work_item_id: str | None
    stage: Literal["input", "output"]
    threat: str | None = Field(description="What the input check saw; null for a reply held back.")
    reason: str
    at: datetime


class GuardrailSummary(StrictModel):
    inputs_blocked: int
    replies_held: int
    by_threat: dict[str, int]
    recent: list[Block]


class LabelTask(StrictModel):
    work_item_id: str
    agent: str
    version_id: str
    rubric: str
    criteria: list[Criterion]
    material: RunMaterial
    reviewed_at: datetime


class LabelRequest(StrictModel):
    work_item_id: str
    agent: str
    verdicts: dict[str, Literal["pass", "fail"]] = Field(min_length=1)


class ReviewRequest(StrictModel):
    work_item_id: str
    agent: str


class LabelOutcome(StrictModel):
    labels: list[QALabel]
    review: ReviewRecord


@router.get("/api/qa/rubrics")
async def rubrics() -> list[Rubric]:
    return [load_rubric(agent) for agent in rubric_agents()]


@router.get("/api/qa/reviews")
async def reviews(
    container: ContainerDep,
    agent: str | None = None,
    version_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ReviewRecord]:
    return await container.quality.store.reviews(agent=agent, version_id=version_id, limit=limit)


@router.post("/api/qa/reviews", status_code=202)
async def request_review(request: ReviewRequest, container: ContainerDep, operator: Operator) -> QaReviewJob:
    run = await container.ledger.get(request.work_item_id, request.agent)
    if run is None:
        raise NotFoundError(f"no run of {request.agent} on {request.work_item_id}")
    if not run.finished:
        raise ConflictError(f"the run of {request.agent} on {request.work_item_id} has not finished")
    job = QaReviewJob(
        work_item_id=WorkItemId(run.work_item_id), agent=run.agent, version_id=run.version_id, reason="requested"
    )
    await container.queue.send(job)
    return job


@router.get("/api/qa/queue")
async def label_queue(
    container: ContainerDep, agent: str | None = None, limit: int = Query(default=1, ge=1, le=20)
) -> list[LabelTask]:
    tasks: list[LabelTask] = []
    for review in await container.quality.store.unlabeled(agent=agent, limit=limit * 3):
        try:
            material = await container.reviews.material(review.work_item_id, review.agent)
        except NotFoundError:
            continue
        rubric = load_rubric(review.agent)
        tasks.append(
            LabelTask(
                work_item_id=review.work_item_id,
                agent=review.agent,
                version_id=review.version_id,
                rubric=review.rubric,
                criteria=list(rubric.criteria),
                material=material,
                reviewed_at=review.created_at,
            )
        )
        if len(tasks) == limit:
            break
    return tasks


@router.post("/api/qa/labels")
async def label(request: LabelRequest, container: ContainerDep, operator: Operator) -> LabelOutcome:
    review = await container.quality.store.review(request.work_item_id, request.agent)
    if review is None:
        raise NotFoundError(f"no review of {request.agent} on {request.work_item_id}")
    unknown = set(request.verdicts) - {criterion.criterion_id for criterion in review.criteria}
    if unknown:
        raise InvalidRequest(f"not criteria of this review: {', '.join(sorted(unknown))}")
    now = container.clock.now()
    labels = [
        QALabel(
            work_item_id=request.work_item_id,
            agent=request.agent,
            criterion_id=criterion_id,
            verdict=verdict,
            labeled_by=operator,
            labeled_at=now,
        )
        for criterion_id, verdict in request.verdicts.items()
    ]
    await container.quality.label(labels)
    return LabelOutcome(labels=labels, review=review)


@router.get("/api/qa/labels")
async def labels(container: ContainerDep, agent: str | None = None) -> list[QALabel]:
    return await container.quality.store.labels(agent=agent)


@router.get("/api/qa/calibration")
async def calibration(container: ContainerDep) -> list[CriterionCalibration]:
    report: list[CriterionCalibration] = []
    for agent in rubric_agents():
        report.extend(await container.quality.calibration_report(agent))
    return report


@router.get("/api/guardrails")
async def guardrails(container: ContainerDep) -> GuardrailSummary:
    return guardrail_summary(await container.events.recent(kinds=[EventKind.GUARDRAIL_BLOCKED], limit=GUARDRAIL_EVENTS))


def guardrail_summary(events: Sequence[Event]) -> GuardrailSummary:
    blocks: list[Block] = []
    for event in events:
        payload = event.payload
        if payload.get("stage") == "output":
            found = payload.get("findings")
            kinds = (
                sorted({str(f.get("kind")) for f in found if isinstance(f, dict)}) if isinstance(found, list) else []
            )
            reason = f"The reply named {', '.join(kinds) or 'something'} it must not."
            blocks.append(
                Block(work_item_id=event.work_item_id, stage="output", threat=None, reason=reason, at=event.occurred_at)
            )
        else:
            blocks.append(
                Block(
                    work_item_id=event.work_item_id,
                    stage="input",
                    threat=str(payload.get("threat") or "unknown"),
                    reason=str(payload.get("reason") or ""),
                    at=event.occurred_at,
                )
            )
    threats: dict[str, int] = {}
    for block in blocks:
        if block.threat is not None:
            threats[block.threat] = threats.get(block.threat, 0) + 1
    return GuardrailSummary(
        inputs_blocked=sum(b.stage == "input" for b in blocks),
        replies_held=sum(b.stage == "output" for b in blocks),
        by_threat=threats,
        recent=blocks[:RECENT_BLOCKS],
    )

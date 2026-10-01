from __future__ import annotations

from collections.abc import Sequence

from pydantic import JsonValue

from ahq.config import QaConfig
from ahq.domain import (
    AgentRun,
    EventKind,
    NewEvent,
    QALabel,
    QaReviewJob,
    ReviewReason,
    ReviewRecord,
    StrictModel,
    WorkItemId,
    review_id_for,
)
from ahq.grading import Calibration, RunMaterial, calibrate, drift, load_rubric, pairs_by_criterion, review_run
from ahq.ports import ChatModels, Clock, EventLog, Limits, QualityStore
from ahq.scorecards import in_share

REVIEWER = "qa"


def review_reason(run: AgentRun, *, canary: bool, config: QaConfig) -> ReviewReason | None:
    if not run.finished or run.outcome == "failed":
        return None
    if canary and config.canary:
        return "canary"
    if run.outcome == "escalated" and config.escalations:
        return "escalation"
    if run.rejected_approvals and config.rejected_approvals:
        return "rejected_approval"
    if in_share(f"qa:{run.agent}:{run.work_item_id}", config.sample_rate):
        return "sample"
    return None


class CriterionCalibration(StrictModel):
    agent: str
    criterion_id: str
    title: str
    safety: bool
    current: Calibration
    history: list[Calibration]


class QualityDesk:
    def __init__(
        self,
        models: ChatModels,
        store: QualityStore,
        limits: Limits,
        events: EventLog,
        clock: Clock,
        config: QaConfig,
    ) -> None:
        self._models = models
        self._store = store
        self._limits = limits
        self._events = events
        self._clock = clock
        self._config = config

    @property
    def store(self) -> QualityStore:
        return self._store

    async def review(self, job: QaReviewJob, material: RunMaterial) -> ReviewRecord | None:
        existing = await self._store.review(job.work_item_id, job.agent)
        if existing is not None:
            return existing
        rubric = load_rubric(job.agent)
        model = self._models.model_key(REVIEWER)
        decision = await self._limits.before_call(REVIEWER, model)
        if decision.verdict in ("pause", "deny"):
            return None
        model = decision.model
        started = self._clock.now()
        try:
            review, report = await review_run(self._models, rubric, material, model=model)
        except Exception as error:
            await self._limits.after_call(REVIEWER, model, cost_usd=0.0, ok=False, error=repr(error))
            raise
        seconds = (self._clock.now() - started).total_seconds()
        cost = report.cost_usd(self._models.price(REVIEWER, model))
        await self._limits.after_call(REVIEWER, model, cost_usd=cost, ok=True)
        record = await self._store.save_review(
            ReviewRecord(
                review_id=review_id_for(job.work_item_id, job.agent),
                work_item_id=job.work_item_id,
                agent=job.agent,
                version_id=job.version_id,
                rubric=rubric.ref,
                judge_model=model,
                reason=job.reason,
                criteria=review.criteria,
                summary=review.summary,
                cost_usd=cost,
                created_at=self._clock.now(),
            )
        )
        verdicts: dict[str, JsonValue] = {c.criterion_id: c.verdict for c in record.criteria}
        payload: dict[str, JsonValue] = {
            "agent": record.agent,
            "version_id": record.version_id,
            "reason": record.reason,
            "verdicts": verdicts,
            "model": model,
            "cost_usd": cost,
            "seconds": round(seconds, 3),
        }
        event = NewEvent(
            kind=EventKind.QA_REVIEWED,
            occurred_at=self._clock.now(),
            work_item_id=WorkItemId(job.work_item_id),
            actor=REVIEWER,
            payload=payload,
        )
        await self._events.append([event])
        return record

    async def label(self, labels: Sequence[QALabel]) -> None:
        await self._store.save_labels(labels)

    async def calibrations(self, agent: str) -> dict[str, Calibration]:
        return {item.criterion_id: item.current for item in await self.calibration_report(agent)}

    async def calibration_report(self, agent: str) -> list[CriterionCalibration]:
        rubric = load_rubric(agent)
        labels = await self._store.labels(agent=agent)
        reviews = await self._store.reviews(agent=agent, limit=5_000)
        pairs = pairs_by_criterion(reviews, labels)
        policy = self._config.calibration
        return [
            CriterionCalibration(
                agent=agent,
                criterion_id=criterion.id,
                title=criterion.title,
                safety=criterion.safety,
                current=calibrate(criterion.id, pairs.get(criterion.id, []), policy),
                history=drift(criterion.id, pairs.get(criterion.id, []), policy),
            )
            for criterion in rubric.criteria
        ]

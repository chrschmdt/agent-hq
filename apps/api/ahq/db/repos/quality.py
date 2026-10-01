from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.db.models import EvalCaseRow, EvalRunRow, QaLabelRow, QaReviewRow
from ahq.domain import (
    ConflictError,
    CriterionVerdict,
    EvalCase,
    EvalRun,
    EvalStatus,
    GateParams,
    GateSummary,
    NotFoundError,
    QALabel,
    ReviewRecord,
)

FINAL_STATUSES = ("passed", "failed", "error")


def _review(row: QaReviewRow) -> ReviewRecord:
    return ReviewRecord(
        review_id=row.review_id,
        work_item_id=row.work_item_id,
        agent=row.agent,
        version_id=row.version_id,
        rubric=row.rubric,
        judge_model=row.judge_model,
        reason=row.reason,  # pyright: ignore[reportArgumentType]
        criteria=[CriterionVerdict.model_validate(item) for item in row.criteria],
        summary=row.summary,
        cost_usd=row.cost_usd,
        created_at=row.created_at,
    )


class PgQualityStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save_review(self, review: ReviewRecord) -> ReviewRecord:
        values = {**review.model_dump(mode="json", exclude={"created_at"}), "created_at": review.created_at}
        async with self._sessions.begin() as session:
            await session.execute(
                insert(QaReviewRow).values(values).on_conflict_do_nothing(index_elements=["work_item_id", "agent"])
            )
            row = await session.scalar(
                select(QaReviewRow).where(
                    QaReviewRow.work_item_id == review.work_item_id, QaReviewRow.agent == review.agent
                )
            )
        assert row is not None
        return _review(row)

    async def review(self, work_item_id: str, agent: str) -> ReviewRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(QaReviewRow).where(QaReviewRow.work_item_id == work_item_id, QaReviewRow.agent == agent)
            )
        return None if row is None else _review(row)

    async def reviews(
        self,
        *,
        agent: str | None = None,
        version_id: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[ReviewRecord]:
        query = select(QaReviewRow).order_by(QaReviewRow.created_at.desc(), QaReviewRow.review_id.desc()).limit(limit)
        if agent is not None:
            query = query.where(QaReviewRow.agent == agent)
        if version_id is not None:
            query = query.where(QaReviewRow.version_id == version_id)
        if since is not None:
            query = query.where(QaReviewRow.created_at >= since)
        async with self._sessions() as session:
            return [_review(row) for row in await session.scalars(query)]

    async def save_labels(self, labels: Sequence[QALabel]) -> None:
        if not labels:
            return
        rows = [label.model_dump() for label in labels]
        statement = insert(QaLabelRow).values(rows)
        async with self._sessions.begin() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["work_item_id", "agent", "criterion_id"],
                    set_={
                        "verdict": statement.excluded.verdict,
                        "labeled_by": statement.excluded.labeled_by,
                        "labeled_at": statement.excluded.labeled_at,
                    },
                )
            )

    async def labels(self, *, agent: str | None = None) -> list[QALabel]:
        query = select(QaLabelRow).order_by(QaLabelRow.labeled_at, QaLabelRow.work_item_id, QaLabelRow.criterion_id)
        if agent is not None:
            query = query.where(QaLabelRow.agent == agent)
        async with self._sessions() as session:
            return [
                QALabel(
                    work_item_id=row.work_item_id,
                    agent=row.agent,
                    criterion_id=row.criterion_id,
                    verdict=row.verdict,  # pyright: ignore[reportArgumentType]
                    labeled_by=row.labeled_by,
                    labeled_at=row.labeled_at,
                )
                for row in await session.scalars(query)
            ]

    async def unlabeled(self, *, agent: str | None = None, limit: int = 20) -> list[ReviewRecord]:
        labeled = exists().where(
            QaLabelRow.work_item_id == QaReviewRow.work_item_id, QaLabelRow.agent == QaReviewRow.agent
        )
        query = (
            select(QaReviewRow)
            .where(~labeled)
            .order_by(QaReviewRow.created_at.desc(), QaReviewRow.review_id.desc())
            .limit(limit)
        )
        if agent is not None:
            query = query.where(QaReviewRow.agent == agent)
        async with self._sessions() as session:
            return [_review(row) for row in await session.scalars(query)]


def _eval_run(row: EvalRunRow) -> EvalRun:
    return EvalRun(
        eval_run_id=row.eval_run_id,
        agent=row.agent,
        candidate_id=row.candidate_id,
        baseline_id=row.baseline_id,
        params=GateParams.model_validate(row.params),
        status=row.status,  # pyright: ignore[reportArgumentType]
        backend=row.backend,  # pyright: ignore[reportArgumentType]
        requested_by=row.requested_by,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        url=row.url,
        summary=GateSummary.model_validate(row.summary) if row.summary is not None else None,
        error=row.error,
        cost_usd=row.cost_usd,
    )


class PgEvalStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, run: EvalRun) -> EvalRun:
        values = {
            **run.model_dump(mode="json", exclude={"created_at", "started_at", "finished_at"}),
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
        async with self._sessions.begin() as session:
            created = await session.scalar(
                insert(EvalRunRow).values(values).on_conflict_do_nothing().returning(EvalRunRow.eval_run_id)
            )
        if created is None:
            raise ConflictError(f"eval run {run.eval_run_id} already exists")
        return run

    async def get(self, eval_run_id: str) -> EvalRun | None:
        async with self._sessions() as session:
            row = await session.get(EvalRunRow, eval_run_id)
        return None if row is None else _eval_run(row)

    async def list(self, *, agent: str | None = None, limit: int = 50) -> list[EvalRun]:
        query = select(EvalRunRow).order_by(EvalRunRow.created_at.desc(), EvalRunRow.eval_run_id.desc()).limit(limit)
        if agent is not None:
            query = query.where(EvalRunRow.agent == agent)
        async with self._sessions() as session:
            return [_eval_run(row) for row in await session.scalars(query)]

    async def update(
        self,
        eval_run_id: str,
        *,
        status: EvalStatus,
        at: datetime,
        url: str | None = None,
        summary: GateSummary | None = None,
        error: str | None = None,
        cost_usd: float | None = None,
    ) -> EvalRun:
        values: dict[str, object] = {"status": status}
        if url is not None:
            values["url"] = url
        if summary is not None:
            values["summary"] = summary.model_dump(mode="json")
        if error is not None:
            values["error"] = error
        if cost_usd is not None:
            values["cost_usd"] = cost_usd
        if status in FINAL_STATUSES:
            values["finished_at"] = at
        async with self._sessions.begin() as session:
            if status == "running":
                await session.execute(
                    update(EvalRunRow)
                    .where(EvalRunRow.eval_run_id == eval_run_id, EvalRunRow.started_at.is_(None))
                    .values(started_at=at)
                )
            row = await session.scalar(
                update(EvalRunRow).where(EvalRunRow.eval_run_id == eval_run_id).values(values).returning(EvalRunRow)
            )
        if row is None:
            raise NotFoundError(f"eval run {eval_run_id} not found")
        return _eval_run(row)

    async def add_cases(self, eval_run_id: str, cases: Sequence[EvalCase]) -> None:
        if not cases:
            return
        rows = [{**case.model_dump(mode="json"), "eval_run_id": eval_run_id} for case in cases]
        statement = insert(EvalCaseRow).values(rows)
        keys = ("eval_run_id", "version_id", "case_id", "trial")
        async with self._sessions.begin() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=list(keys),
                    set_={column: statement.excluded[column] for column in rows[0] if column not in keys},
                )
            )

    async def cases(self, eval_run_id: str) -> list[EvalCase]:
        query = (
            select(EvalCaseRow)
            .where(EvalCaseRow.eval_run_id == eval_run_id)
            .order_by(EvalCaseRow.version_id, EvalCaseRow.case_id, EvalCaseRow.trial)
        )
        async with self._sessions() as session:
            return [
                EvalCase(
                    version_id=row.version_id,
                    case_id=row.case_id,
                    trial=row.trial,
                    passed=row.passed,
                    score=row.score,
                    cost_usd=row.cost_usd,
                    seconds=row.seconds,
                    detail=row.detail,
                )
                for row in await session.scalars(query)
            ]

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ahq.domain import EvalCase, EvalRun, EvalStatus, GateSummary, QALabel, ReviewRecord


class QualityStore(Protocol):
    async def save_review(self, review: ReviewRecord) -> ReviewRecord: ...

    async def review(self, work_item_id: str, agent: str) -> ReviewRecord | None: ...

    async def reviews(
        self,
        *,
        agent: str | None = None,
        version_id: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[ReviewRecord]: ...

    async def save_labels(self, labels: Sequence[QALabel]) -> None: ...

    async def labels(self, *, agent: str | None = None) -> list[QALabel]: ...

    async def unlabeled(self, *, agent: str | None = None, limit: int = 20) -> list[ReviewRecord]: ...


class EvalStore(Protocol):
    async def create(self, run: EvalRun) -> EvalRun: ...

    async def get(self, eval_run_id: str) -> EvalRun | None: ...

    async def list(self, *, agent: str | None = None, limit: int = 50) -> list[EvalRun]: ...

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
    ) -> EvalRun: ...

    async def add_cases(self, eval_run_id: str, cases: Sequence[EvalCase]) -> None: ...

    async def cases(self, eval_run_id: str) -> list[EvalCase]: ...


class EvalLauncher(Protocol):
    async def launch(self, run: EvalRun) -> None: ...

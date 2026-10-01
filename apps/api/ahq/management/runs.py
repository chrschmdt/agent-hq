from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from ahq.config import BudgetConfig, QaConfig
from ahq.domain import AgentRun, QaReviewJob, WorkItemId
from ahq.management.canary import CanaryWatch
from ahq.management.limits import Limiter
from ahq.management.quality import review_reason
from ahq.management.versions import VersionRegistry
from ahq.ports import Clock, Queue, RunLedger

BREAKER = "breaker"


class RunDesk:
    def __init__(
        self,
        ledger: RunLedger,
        queue: Queue,
        registry: VersionRegistry,
        canary: CanaryWatch,
        limiter: Limiter,
        clock: Clock,
        *,
        qa: QaConfig,
        budgets: BudgetConfig,
    ) -> None:
        self._ledger = ledger
        self._queue = queue
        self._registry = registry
        self._canary = canary
        self._limiter = limiter
        self._clock = clock
        self._qa = qa
        self._budgets = budgets

    async def after_run(self, runs: Sequence[AgentRun]) -> None:
        await self._ledger.record(runs)
        for run in runs:
            if not run.finished:
                continue
            serving = await self._registry.serving(run.agent)
            on_canary = serving.canary is not None and serving.canary.version_id == run.version_id
            reason = review_reason(run, canary=on_canary, config=self._qa)
            if reason is not None:
                job = QaReviewJob(
                    work_item_id=WorkItemId(run.work_item_id),
                    agent=run.agent,
                    version_id=run.version_id,
                    reason=reason,
                )
                await self._queue.send(job)
            if serving.canary is not None:
                await self._canary.check(run.agent)

    async def after_failure(self, runs: Sequence[AgentRun]) -> None:
        await self._ledger.record(runs)
        breaker = self._budgets.agent_breaker
        since = self._clock.now() - timedelta(minutes=breaker.window_minutes)
        paused = await self._limiter.paused()
        for run in runs:
            if run.outcome != "failed":
                continue
            recent = await self._ledger.runs(agent=run.agent, since=since, finished=True)
            failures = sum(r.outcome == "failed" for r in recent)
            if failures >= breaker.failures and run.agent not in paused:
                reason = f"{failures} failed runs in {breaker.window_minutes:g} minutes"
                await self._limiter.pause(run.agent, by=BREAKER, reason=reason)
                paused = paused | {run.agent}
            await self._canary.check(run.agent)

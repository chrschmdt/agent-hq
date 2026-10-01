from __future__ import annotations

from ahq.config import CanaryConfig
from ahq.domain import AgentVersion, ConflictError
from ahq.grading import load_rubric
from ahq.management.quality import QualityDesk
from ahq.management.versions import VersionRegistry
from ahq.ports import RunLedger
from ahq.scorecards import CanaryDecision, Scorecard, compute_scorecard, decide_canary

WATCH = "canary"


class CanaryWatch:
    def __init__(
        self, registry: VersionRegistry, ledger: RunLedger, quality: QualityDesk, config: CanaryConfig
    ) -> None:
        self._registry = registry
        self._ledger = ledger
        self._quality = quality
        self._config = config

    async def scorecards(self, agent: str) -> tuple[Scorecard, Scorecard] | None:
        serving = await self._registry.serving(agent)
        if serving.canary is None or serving.live is None:
            return None
        return (
            await self._card(serving.canary, since_canary=serving.canary),
            await self._card(serving.live, since_canary=serving.canary),
        )

    async def check(self, agent: str) -> CanaryDecision | None:
        cards = await self.scorecards(agent)
        if cards is None:
            return None
        canary, live = cards
        decision = decide_canary(canary, live, self._config)
        try:
            if decision.action == "rollback":
                await self._registry.roll_back(canary.version_id, by=WATCH, reasons=decision.reasons)
            elif decision.action == "promote" and self._config.auto_promote:
                await self._registry.promote(canary.version_id, by=WATCH, reason="; ".join(decision.reasons))
        except ConflictError:
            return None
        return decision

    async def _card(self, version: AgentVersion, *, since_canary: AgentVersion) -> Scorecard:
        since = since_canary.status_at
        runs = await self._ledger.runs(version_id=version.version_id, finished=True, since=since)
        if version.version_id != since_canary.version_id and len(runs) < self._config.min_runs:
            runs = await self._ledger.runs(
                version_id=version.version_id, finished=True, limit=self._config.baseline_runs
            )
        reviews = await self._quality.store.reviews(version_id=version.version_id, limit=1_000)
        chosen = {run.work_item_id for run in runs}
        rubric = load_rubric(version.agent)
        return compute_scorecard(
            version.agent,
            version.version_id,
            runs,
            [review for review in reviews if review.work_item_id in chosen],
            await self._quality.calibrations(version.agent),
            safety=[criterion.id for criterion in rubric.criteria if criterion.safety],
        )

from __future__ import annotations

import asyncio
from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta

from pydantic import JsonValue

from ahq.domain import (
    AgentControl,
    AgentRun,
    AgentVersion,
    ConflictError,
    EvalCase,
    EvalRun,
    EvalStatus,
    GateSummary,
    ModelChoice,
    ModelHealth,
    NotFoundError,
    QALabel,
    ReviewRecord,
    Serving,
    SpendLine,
    VersionStatus,
)

UNIQUE_STATUSES = frozenset({VersionStatus.LIVE, VersionStatus.CANARY})
FINAL_EVAL_STATUSES: frozenset[EvalStatus] = frozenset({"passed", "failed", "error"})


class MemoryVersionStore:
    def __init__(self) -> None:
        self._versions: dict[str, AgentVersion] = {}
        self._lock = asyncio.Lock()

    async def create(self, version: AgentVersion) -> AgentVersion:
        async with self._lock:
            for existing in self._versions.values():
                if existing.agent == version.agent and existing.digest == version.digest:
                    return existing
            if version.version_id in self._versions:
                raise ConflictError(f"version {version.version_id} already exists")
            self._check_unique(version.agent, version.status, version.version_id)
            self._versions[version.version_id] = version
            return version

    async def get(self, version_id: str) -> AgentVersion | None:
        return self._versions.get(version_id)

    async def list(self, agent: str | None = None) -> list[AgentVersion]:
        chosen = [v for v in self._versions.values() if agent is None or v.agent == agent]
        return sorted(chosen, key=lambda v: (v.created_at, v.number), reverse=True)

    async def serving(self, agent: str) -> Serving:
        mine = [v for v in self._versions.values() if v.agent == agent]
        return Serving(
            live=next((v for v in mine if v.status is VersionStatus.LIVE), None),
            canary=next((v for v in mine if v.status is VersionStatus.CANARY), None),
        )

    async def next_number(self, agent: str) -> int:
        return max((v.number for v in self._versions.values() if v.agent == agent), default=0) + 1

    async def set_status(
        self,
        version_id: str,
        status: VersionStatus,
        *,
        expected: Collection[VersionStatus],
        at: datetime,
        reason: str | None = None,
        canary_pct: int | None = None,
    ) -> AgentVersion:
        async with self._lock:
            version = self._require(version_id, expected)
            self._check_unique(version.agent, status, version_id)
            update: dict[str, object] = {"status": status, "status_at": at, "status_reason": reason}
            if canary_pct is not None:
                update["canary_pct"] = canary_pct
            moved = version.model_copy(update=update)
            self._versions[version_id] = moved
            return moved

    async def promote(
        self, version_id: str, *, expected: Collection[VersionStatus], at: datetime, reason: str
    ) -> tuple[AgentVersion, AgentVersion | None]:
        async with self._lock:
            version = self._require(version_id, expected)
            retired: AgentVersion | None = None
            for other in self._versions.values():
                if other.agent == version.agent and other.status is VersionStatus.LIVE:
                    retired = other.model_copy(
                        update={"status": VersionStatus.RETIRED, "status_at": at, "status_reason": f"{version_id} live"}
                    )
                    self._versions[other.version_id] = retired
            live = version.model_copy(update={"status": VersionStatus.LIVE, "status_at": at, "status_reason": reason})
            self._versions[version_id] = live
            return live, retired

    async def set_eval_summary(self, version_id: str, summary: dict[str, JsonValue]) -> AgentVersion:
        version = self._versions.get(version_id)
        if version is None:
            raise NotFoundError(f"version {version_id} not found")
        updated = version.model_copy(update={"eval_summary": summary})
        self._versions[version_id] = updated
        return updated

    def _require(self, version_id: str, expected: Collection[VersionStatus]) -> AgentVersion:
        version = self._versions.get(version_id)
        if version is None:
            raise NotFoundError(f"version {version_id} not found")
        if version.status not in expected:
            raise ConflictError(f"version {version_id} is {version.status}")
        return version

    def _check_unique(self, agent: str, status: VersionStatus, version_id: str) -> None:
        if status not in UNIQUE_STATUSES:
            return
        for other in self._versions.values():
            if other.agent == agent and other.status is status and other.version_id != version_id:
                raise ConflictError(f"{agent} already has a {status} version, {other.version_id}")

    def clear_versions(self) -> dict[str, int]:
        count = len(self._versions)
        self._versions = {}
        return {"agents.agent_versions": count}


class MemoryRunLedger:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], AgentRun] = {}

    async def record(self, runs: Sequence[AgentRun]) -> None:
        for run in runs:
            self._runs[run.work_item_id, run.agent] = run

    async def get(self, work_item_id: str, agent: str) -> AgentRun | None:
        return self._runs.get((work_item_id, agent))

    async def runs(
        self,
        *,
        agent: str | None = None,
        version_id: str | None = None,
        finished: bool | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[AgentRun]:
        chosen = [
            run
            for run in self._runs.values()
            if (agent is None or run.agent == agent)
            and (version_id is None or run.version_id == version_id)
            and (finished is None or run.finished == finished)
            and (since is None or run.updated_at >= since)
        ]
        return sorted(chosen, key=lambda run: (run.updated_at, run.work_item_id), reverse=True)[:limit]

    def clear_activity(self) -> dict[str, int]:
        count = len(self._runs)
        self._runs = {}
        return {"agents.agent_runs": count}


class MemorySlots:
    def __init__(self) -> None:
        self._held: dict[tuple[str, int], tuple[str, datetime]] = {}
        self._lock = asyncio.Lock()
        self.peaks: dict[str, int] = {}

    async def acquire(self, provider: str, holder: str, *, limit: int, now: datetime, until: datetime) -> bool:
        async with self._lock:
            for slot in range(limit):
                current = self._held.get((provider, slot))
                if current is None or current[1] <= now:
                    self._held[provider, slot] = (holder, until)
                    self.peaks[provider] = max(self.peaks.get(provider, 0), self.held(provider, now))
                    return True
            return False

    async def release(self, provider: str, holder: str) -> None:
        async with self._lock:
            for key, (held_by, _) in list(self._held.items()):
                if key[0] == provider and held_by == holder:
                    del self._held[key]

    def held(self, provider: str, now: datetime) -> int:
        return sum(key[0] == provider and until > now for key, (_, until) in self._held.items())

    def clear_activity(self) -> dict[str, int]:
        count = len(self._held)
        self._held = {}
        return {"agents.provider_slots": count}


class MemoryControlStore:
    def __init__(self) -> None:
        self._controls: dict[str, AgentControl] = {}
        self._choice: ModelChoice | None = None
        self._spend: dict[tuple[date, str, str], SpendLine] = {}
        self._health: dict[str, ModelHealth] = {}
        self._lock = asyncio.Lock()

    async def controls(self) -> dict[str, AgentControl]:
        return dict(self._controls)

    async def set_control(self, control: AgentControl) -> AgentControl:
        self._controls[control.agent] = control
        return control

    async def model_choice(self) -> ModelChoice | None:
        return self._choice

    async def set_model_choice(self, choice: ModelChoice) -> ModelChoice:
        self._choice = choice
        return choice

    async def spend(self, day: date) -> list[SpendLine]:
        return [line for (spent_on, _, _), line in sorted(self._spend.items()) if spent_on == day]

    async def add_spend(self, day: date, agent: str, model: str, *, cost_usd: float, ok: bool) -> None:
        async with self._lock:
            line = self._spend.get((day, agent, model)) or SpendLine(
                day=day, agent=agent, model=model, calls=0, errors=0, cost_usd=0.0
            )
            self._spend[day, agent, model] = line.model_copy(
                update={
                    "calls": line.calls + 1,
                    "errors": line.errors + (0 if ok else 1),
                    "cost_usd": line.cost_usd + cost_usd,
                }
            )

    async def health(self) -> dict[str, ModelHealth]:
        return dict(self._health)

    async def record_call(
        self, model: str, *, ok: bool, at: datetime, errors_to_open: int, cooldown: timedelta, error: str | None = None
    ) -> tuple[ModelHealth, bool]:
        async with self._lock:
            current = self._health.get(model) or ModelHealth(model=model, consecutive_errors=0, updated_at=at)
            if ok:
                if current.consecutive_errors == 0 and current.open_until is None:
                    return current, False
                healed = ModelHealth(model=model, consecutive_errors=0, last_error=current.last_error, updated_at=at)
                self._health[model] = healed
                return healed, False
            errors = current.consecutive_errors + 1
            opens = errors >= errors_to_open and not current.is_open(at)
            health = ModelHealth(
                model=model,
                consecutive_errors=errors,
                open_until=at + cooldown if opens else current.open_until,
                last_error=error,
                updated_at=at,
            )
            self._health[model] = health
            return health, opens

    def clear_activity(self) -> dict[str, int]:
        counts = {
            "agents.spend_daily": len(self._spend),
            "agents.model_health": len(self._health),
            "agents.agent_controls": len(self._controls),
        }
        self._controls, self._spend, self._health = {}, {}, {}
        return counts


class MemoryQualityStore:
    def __init__(self) -> None:
        self._reviews: dict[tuple[str, str], ReviewRecord] = {}
        self._labels: dict[tuple[str, str, str], QALabel] = {}

    async def save_review(self, review: ReviewRecord) -> ReviewRecord:
        return self._reviews.setdefault((review.work_item_id, review.agent), review)

    async def review(self, work_item_id: str, agent: str) -> ReviewRecord | None:
        return self._reviews.get((work_item_id, agent))

    async def reviews(
        self,
        *,
        agent: str | None = None,
        version_id: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[ReviewRecord]:
        chosen = [
            review
            for review in self._reviews.values()
            if (agent is None or review.agent == agent)
            and (version_id is None or review.version_id == version_id)
            and (since is None or review.created_at >= since)
        ]
        return sorted(chosen, key=lambda review: (review.created_at, review.review_id), reverse=True)[:limit]

    async def save_labels(self, labels: Sequence[QALabel]) -> None:
        for label in labels:
            self._labels[label.work_item_id, label.agent, label.criterion_id] = label

    async def labels(self, *, agent: str | None = None) -> list[QALabel]:
        chosen = [label for label in self._labels.values() if agent is None or label.agent == agent]
        return sorted(chosen, key=lambda label: (label.labeled_at, label.work_item_id, label.criterion_id))

    async def unlabeled(self, *, agent: str | None = None, limit: int = 20) -> list[ReviewRecord]:
        labeled = {(label.work_item_id, label.agent) for label in self._labels.values()}
        waiting = [
            review
            for key, review in self._reviews.items()
            if key not in labeled and (agent is None or review.agent == agent)
        ]
        return sorted(waiting, key=lambda review: (review.created_at, review.review_id), reverse=True)[:limit]

    def clear_activity(self) -> dict[str, int]:
        counts = {"agents.qa_labels": len(self._labels), "agents.qa_reviews": len(self._reviews)}
        self._reviews, self._labels = {}, {}
        return counts


class MemoryEvalStore:
    def __init__(self) -> None:
        self._runs: dict[str, EvalRun] = {}
        self._cases: dict[str, dict[tuple[str, str, int], EvalCase]] = {}

    async def create(self, run: EvalRun) -> EvalRun:
        if run.eval_run_id in self._runs:
            raise ConflictError(f"eval run {run.eval_run_id} already exists")
        self._runs[run.eval_run_id] = run
        return run

    async def get(self, eval_run_id: str) -> EvalRun | None:
        return self._runs.get(eval_run_id)

    async def list(self, *, agent: str | None = None, limit: int = 50) -> list[EvalRun]:
        chosen = [run for run in self._runs.values() if agent is None or run.agent == agent]
        return sorted(chosen, key=lambda run: (run.created_at, run.eval_run_id), reverse=True)[:limit]

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
        run = self._runs.get(eval_run_id)
        if run is None:
            raise NotFoundError(f"eval run {eval_run_id} not found")
        update: dict[str, object] = {"status": status}
        if status == "running" and run.started_at is None:
            update["started_at"] = at
        if status in FINAL_EVAL_STATUSES:
            update["finished_at"] = at
        for key, value in (("url", url), ("summary", summary), ("error", error), ("cost_usd", cost_usd)):
            if value is not None:
                update[key] = value
        moved = run.model_copy(update=update)
        self._runs[eval_run_id] = moved
        return moved

    async def add_cases(self, eval_run_id: str, cases: Sequence[EvalCase]) -> None:
        stored = self._cases.setdefault(eval_run_id, {})
        for case in cases:
            stored[case.version_id, case.case_id, case.trial] = case

    async def cases(self, eval_run_id: str) -> list[EvalCase]:
        return sorted(self._cases.get(eval_run_id, {}).values(), key=lambda c: (c.version_id, c.case_id, c.trial))

    def clear_activity(self) -> dict[str, int]:
        counts = {"agents.eval_cases": sum(map(len, self._cases.values())), "agents.eval_runs": len(self._runs)}
        self._runs, self._cases = {}, {}
        return counts

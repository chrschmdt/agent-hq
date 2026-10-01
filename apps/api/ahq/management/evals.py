from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import JsonValue

from ahq.config import CanaryConfig
from ahq.domain import (
    ConfigurationError,
    ConflictError,
    EvalBackend,
    EvalCase,
    EvalRun,
    EvalStatus,
    EventKind,
    GateParams,
    GateSummary,
    NewEvent,
    NotFoundError,
    VersionStatus,
    new_eval_run_id,
)
from ahq.domain.evals import ProfileChoice
from ahq.management.versions import VersionRegistry
from ahq.ports import Clock, EvalLauncher, EvalStore, EventLog

GATE = "eval"


class EvalDesk:
    def __init__(
        self,
        store: EvalStore,
        registry: VersionRegistry,
        launcher: EvalLauncher | None,
        events: EventLog,
        clock: Clock,
        config: CanaryConfig,
        *,
        backend: EvalBackend,
        profile: Callable[[], ProfileChoice],
    ) -> None:
        self._store = store
        self._registry = registry
        self._launcher = launcher
        self._events = events
        self._clock = clock
        self._config = config
        self._backend: EvalBackend = backend
        self._profile = profile

    @property
    def store(self) -> EvalStore:
        return self._store

    def default_params(self, agent: str) -> GateParams:
        suite = self._config.gate.suites.get(agent)
        if suite is None:
            raise NotFoundError(f"no eval suite for {agent}")
        return GateParams(suite=suite.suite, cases=suite.cases, trials=suite.trials, profile=self._profile())

    async def request(
        self, candidate_id: str, *, by: str, params: GateParams | None = None, launch: bool = True
    ) -> EvalRun:
        if launch and self._launcher is None:
            raise ConfigurationError("eval gate runs need AHQ_GITHUB_TOKEN and AHQ_GITHUB_REPO on this deployment")
        candidate = await self._registry.get(candidate_id)
        if candidate.status not in (VersionStatus.DRAFT, VersionStatus.EVALUATED):
            raise ConflictError(f"{candidate_id} is {candidate.status}; only drafts and evaluated versions are gated")
        live = (await self._registry.serving(candidate.agent)).live
        if live is None:
            raise ConflictError(f"{candidate.agent} has no live version to compare with")
        run = await self._store.create(
            EvalRun(
                eval_run_id=new_eval_run_id(),
                agent=candidate.agent,
                candidate_id=candidate_id,
                baseline_id=live.version_id,
                params=params or self.default_params(candidate.agent),
                status="queued",
                backend=self._backend if launch else "cli",
                requested_by=by,
                created_at=self._clock.now(),
            )
        )
        await self._emit(EventKind.EVAL_QUEUED, run, by, {})
        if launch and self._launcher is not None:
            try:
                await self._launcher.launch(run)
            except ConfigurationError as refused:
                await self.finish(run.eval_run_id, [], None, error=str(refused))
                raise
        return run

    async def started(self, eval_run_id: str, *, url: str | None = None) -> EvalRun:
        run = await self._store.update(eval_run_id, status="running", at=self._clock.now(), url=url)
        await self._emit(EventKind.EVAL_STARTED, run, GATE, {"url": url})
        return run

    async def finish(
        self,
        eval_run_id: str,
        cases: Sequence[EvalCase],
        summary: GateSummary | None,
        *,
        error: str | None = None,
        cost_usd: float = 0.0,
        url: str | None = None,
    ) -> EvalRun:
        run = await self._store.get(eval_run_id)
        if run is None:
            raise NotFoundError(f"eval run {eval_run_id} not found")
        if run.status in ("passed", "failed", "error"):
            raise ConflictError(f"eval run {eval_run_id} already finished")
        await self._store.add_cases(eval_run_id, cases)
        status: EvalStatus = "error" if summary is None else ("passed" if summary.passed else "failed")
        finished = await self._store.update(
            eval_run_id, status=status, at=self._clock.now(), summary=summary, error=error, cost_usd=cost_usd, url=url
        )
        if summary is not None:
            recorded: dict[str, JsonValue] = {
                "eval_run_id": eval_run_id,
                **summary.model_dump(mode="json"),
            }
            await self._registry.record_eval(run.candidate_id, recorded, summary.passed)
        await self._emit(EventKind.EVAL_FINISHED, finished, GATE, {"error": error})
        return finished

    async def _emit(self, kind: EventKind, run: EvalRun, by: str, extra: dict[str, JsonValue]) -> None:
        payload: dict[str, JsonValue] = {
            "eval_run_id": run.eval_run_id,
            "agent": run.agent,
            "candidate_id": run.candidate_id,
            "baseline_id": run.baseline_id,
            "status": run.status,
            **extra,
        }
        await self._events.append([NewEvent(kind=kind, occurred_at=self._clock.now(), actor=by, payload=payload)])

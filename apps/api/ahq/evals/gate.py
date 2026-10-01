from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ahq.adapters.clock import WallClock
from ahq.agents import SPECS, AgentSpec, spec_from_version
from ahq.app.container import Container, make_chat_models
from ahq.config import load_canary_config, load_model_catalog
from ahq.domain import AgentVersion, EvalCase, EvalRun, GateParams, GateSummary, VersionScore
from ahq.evals.dispatcher import load_cases, run_dispatcher_eval
from ahq.evals.scenarios import check_scenario
from ahq.evals.tau3 import run_tau3
from ahq.grading import load_split, load_tasks
from ahq.retail import load_snapshot
from ahq.scorecards import judge_gate
from ahq.settings import REPO_ROOT, TAU3_VERSION, Settings

GATE_SCENARIO = "carrier-delay"
GATE_SEED = 7
DISPATCHER_CASES = REPO_ROOT / "evals" / "datasets" / "dispatcher_routes.jsonl"

type Suite = Callable[[Settings, GateParams, AgentSpec, float], Awaitable[tuple[VersionScore, list[EvalCase]]]]


@dataclass(frozen=True)
class GateResult:
    cases: list[EvalCase]
    summary: GateSummary
    cost_usd: float


async def run_gate(settings: Settings, run: EvalRun, candidate: AgentVersion, baseline: AgentVersion) -> GateResult:
    run_settings = settings.model_copy(update={"model_profile": run.params.profile})
    suite = SUITES[run.params.suite]
    half = run.params.max_usd / 2
    candidate_score, candidate_cases = await suite(run_settings, run.params, _spec(candidate), half)
    baseline_score, baseline_cases = await suite(run_settings, run.params, _spec(baseline), half)
    verdict = judge_gate(candidate_score, baseline_score, load_canary_config().gate)
    summary = GateSummary(
        candidate=candidate_score, baseline=baseline_score, passed=verdict.passed, reasons=verdict.reasons
    )
    cost = round(candidate_score.cost_usd + baseline_score.cost_usd, 6)
    return GateResult(cases=candidate_cases + baseline_cases, summary=summary, cost_usd=cost)


def _spec(version: AgentVersion) -> AgentSpec:
    return spec_from_version(SPECS[version.agent], version)


async def _tau3(
    settings: Settings, params: GateParams, spec: AgentSpec, max_usd: float
) -> tuple[VersionScore, list[EvalCase]]:
    tau3 = settings.data_dir / "tau3" / TAU3_VERSION
    catalog = load_tasks(tau3 / "tasks.json")
    tasks = [catalog[task_id] for task_id in load_split(tau3 / "split_tasks.json", "train")[: params.cases]]
    report = await run_tau3(
        settings,
        tasks,
        load_snapshot(tau3 / "db.json"),
        split="train",
        trials=params.trials,
        max_usd=max_usd,
        versions={spec.name: spec},
    )
    cases = [
        EvalCase(
            version_id=spec.version_id,
            case_id=result.task_id,
            trial=result.trial,
            passed=result.reward == 1.0,
            score=result.reward,
            cost_usd=result.cost_usd,
            seconds=result.seconds,
            detail={"db_match": result.db_match, "outcome": result.outcome, "error": result.error},
        )
        for result in report.results
    ]
    pass_k: dict[str, Any] = {str(k): value for k, value in report.pass_k.items()}
    return _score(spec, "pass^1", report.pass_k.get(1, 0.0), cases, report.cost_usd, {"pass_k": pass_k}), cases


async def _dispatcher(
    settings: Settings, params: GateParams, spec: AgentSpec, max_usd: float
) -> tuple[VersionScore, list[EvalCase]]:
    labeled = load_cases(DISPATCHER_CASES)
    step = max(1, len(labeled) // params.cases)
    chosen = labeled[::step][: params.cases]
    report = await run_dispatcher_eval(
        make_chat_models(settings, load_model_catalog()),
        chosen,
        profile=settings.model_profile,
        started_at=WallClock().now(),
        max_usd=max_usd,
        spec=spec,
    )
    cases = [
        EvalCase(
            version_id=spec.version_id,
            case_id=case.case_id,
            trial=0,
            passed=report.decisions[case.case_id].route == case.route,
            score=float(report.decisions[case.case_id].route == case.route),
            cost_usd=0.0,
            seconds=0.0,
            detail={"expected": case.route, "chosen": report.decisions[case.case_id].route},
        )
        for case in chosen
        if case.case_id in report.decisions
    ]
    return _score(spec, "accuracy", report.scores.accuracy, cases, report.cost_usd, {}), cases


async def _scenario(
    settings: Settings, params: GateParams, spec: AgentSpec, max_usd: float
) -> tuple[VersionScore, list[EvalCase]]:
    report = await check_scenario(
        settings,
        GATE_SCENARIO,
        seed=GATE_SEED,
        trials=params.cases * params.trials,
        max_usd=max_usd,
        versions={spec.name: spec},
    )
    cases = [
        EvalCase(
            version_id=spec.version_id,
            case_id=f"{GATE_SCENARIO}:{trial.seed}",
            trial=0,
            passed=trial.passed,
            score=float(trial.passed),
            cost_usd=trial.cost_usd,
            seconds=trial.seconds,
            detail={"expectations": [e.model_dump(mode="json") for e in trial.expectations], "error": trial.error},
        )
        for trial in report.trials
    ]
    return _score(spec, "days passed", report.pass_rate, cases, report.cost_usd, {}), cases


def _score(
    spec: AgentSpec, metric: str, score: float, cases: list[EvalCase], cost: float, details: dict[str, Any]
) -> VersionScore:
    return VersionScore(
        version_id=spec.version_id,
        metric=metric,
        score=round(score, 4),
        cases=len(cases),
        passed=sum(case.passed for case in cases),
        cost_usd=round(cost, 6),
        details=details,
    )


SUITES: dict[str, Suite] = {"tau3": _tau3, "dispatcher": _dispatcher, "scenario": _scenario}


async def run_queued(container: Container, eval_run_id: str) -> None:
    run = await container.evals.store.get(eval_run_id)
    if run is None or run.status != "queued":
        return
    await container.evals.started(eval_run_id)
    candidate = await container.versions.get(run.candidate_id)
    baseline = await container.versions.get(run.baseline_id)
    try:
        result = await run_gate(container.settings, run, candidate, baseline)
    except Exception as failure:  # a failed gate run is recorded, not raised into the queue
        await container.evals.finish(eval_run_id, [], None, error=f"{type(failure).__name__}: {failure}")
        return
    await container.evals.finish(eval_run_id, result.cases, result.summary, cost_usd=result.cost_usd)


class RemoteRun:
    def __init__(
        self, api_url: str, token: str, eval_run_id: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=30, transport=transport
        )
        self._id = eval_run_id

    async def load(self) -> tuple[EvalRun, AgentVersion, AgentVersion]:
        run = EvalRun.model_validate(await self._get(f"/api/evals/{self._id}"))
        candidate = AgentVersion.model_validate(await self._get(f"/api/versions/{run.candidate_id}"))
        baseline = AgentVersion.model_validate(await self._get(f"/api/versions/{run.baseline_id}"))
        return run, candidate, baseline

    async def started(self, url: str | None) -> None:
        await self._post(f"/api/evals/{self._id}/started", {"url": url})

    async def report(self, result: GateResult | None, *, error: str | None = None, url: str | None = None) -> None:
        body: dict[str, Any] = {
            "cases": [case.model_dump(mode="json") for case in result.cases] if result else [],
            "summary": result.summary.model_dump(mode="json") if result else None,
            "cost_usd": result.cost_usd if result else 0.0,
            "error": error,
            "url": url,
        }
        await self._post(f"/api/evals/{self._id}/report", body)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> Any:
        response = await self._client.get(path)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, body: dict[str, Any]) -> None:
        response = await self._client.post(path, json=body)
        response.raise_for_status()

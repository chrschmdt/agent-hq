from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field

from ahq.agents import SPECS
from ahq.api.deps import ContainerDep, Operator
from ahq.domain import EvalBackend, EvalCase, EvalRun, GateParams, GateSummary, NotFoundError, StrictModel

router = APIRouter(tags=["evals"])


class EvalSettings(StrictModel):
    backend: EvalBackend
    suites: dict[str, GateParams]


class StartedReport(StrictModel):
    url: str | None = None


class FinishedReport(StrictModel):
    cases: list[EvalCase] = Field(default_factory=list)
    summary: GateSummary | None = None
    cost_usd: float = Field(default=0.0, ge=0)
    error: str | None = None
    url: str | None = None


@router.get("/api/evals")
async def list_evals(container: ContainerDep, agent: str | None = None) -> list[EvalRun]:
    return await container.evals.store.list(agent=agent)


@router.get("/api/evals/settings")
async def eval_settings(container: ContainerDep) -> EvalSettings:
    suites = {agent: container.evals.default_params(agent) for agent in SPECS}
    return EvalSettings(backend=container.settings.evals_run_on, suites=suites)


@router.get("/api/evals/{eval_run_id}")
async def get_eval(eval_run_id: str, container: ContainerDep) -> EvalRun:
    run = await container.evals.store.get(eval_run_id)
    if run is None:
        raise NotFoundError(f"eval run {eval_run_id} not found")
    return run


@router.get("/api/evals/{eval_run_id}/cases")
async def eval_cases(eval_run_id: str, container: ContainerDep) -> list[EvalCase]:
    return await container.evals.store.cases(eval_run_id)


@router.post("/api/evals/{eval_run_id}/started")
async def eval_started(eval_run_id: str, report: StartedReport, container: ContainerDep, operator: Operator) -> EvalRun:
    return await container.evals.started(eval_run_id, url=report.url)


@router.post("/api/evals/{eval_run_id}/report")
async def eval_report(eval_run_id: str, report: FinishedReport, container: ContainerDep, operator: Operator) -> EvalRun:
    return await container.evals.finish(
        eval_run_id, report.cases, report.summary, error=report.error, cost_usd=report.cost_usd, url=report.url
    )

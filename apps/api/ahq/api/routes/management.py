from __future__ import annotations

import math
from datetime import timedelta

from fastapi import APIRouter
from pydantic import Field

from ahq.agents import SPECS
from ahq.api.deps import ContainerDep, Operator
from ahq.config import load_canary_config, load_roi_config
from ahq.domain import (
    AgentControl,
    AgentRun,
    AgentVersion,
    NotFoundError,
    StrictModel,
    VersionStatus,
    WorkKind,
)
from ahq.domain.world import Ticket
from ahq.grading import load_rubric
from ahq.management import LimitsView
from ahq.scorecards import (
    SCORECARD,
    CanaryDecision,
    MetricDef,
    Scorecard,
    TeamValue,
    TrendPoint,
    compute_scorecard,
    decide_canary,
    team_value,
    trend,
)

router = APIRouter(tags=["management"])

VERSIONS_SHOWN = 6
TREND_POINTS = 12
MIN_WINDOW = 3
VALUE_ITEMS = 5_000
COMPLAINTS_BEFORE = timedelta(days=7)


class PauseRequest(StrictModel):
    reason: str = Field(min_length=3)


class VersionCard(StrictModel):
    version: AgentVersion
    scorecard: Scorecard
    trend: list[TrendPoint]


class AgentScorecards(StrictModel):
    agent: str
    metrics: list[MetricDef]
    versions: list[VersionCard]
    canary: CanaryDecision | None = None


@router.get("/api/value")
async def value(container: ContainerDep) -> TeamValue:
    items = await container.work.list(kinds=[WorkKind.TICKET], limit=VALUE_ITEMS)
    runs = await container.ledger.runs(limit=VALUE_ITEMS * 3)
    incidents = await container.records.incidents(VALUE_ITEMS)
    complaints: list[Ticket] = []
    if incidents:
        first = min(incident.detected_at for incident in incidents)
        last = max(incident.detected_at for incident in incidents)
        complaints = await container.world.tickets_opened(first - COMPLAINTS_BEFORE, last)
    return team_value(
        items,
        runs,
        incidents,
        await container.world.shipments() if incidents else [],
        complaints,
        human_cost_per_ticket_usd=load_roi_config().human_cost_per_ticket_usd,
    )


@router.get("/api/limits")
async def limits(container: ContainerDep, _: Operator) -> LimitsView:
    return await container.limiter.view([*SPECS, "qa"])


@router.post("/api/agents/{agent}/pause")
async def pause(agent: str, request: PauseRequest, container: ContainerDep, operator: Operator) -> AgentControl:
    if agent not in SPECS:
        raise NotFoundError(f"agent {agent} not found")
    return await container.limiter.pause(agent, by=operator, reason=request.reason)


@router.post("/api/agents/{agent}/resume")
async def resume(agent: str, container: ContainerDep, operator: Operator) -> AgentControl:
    if agent not in SPECS:
        raise NotFoundError(f"agent {agent} not found")
    return await container.limiter.resume(agent, by=operator)


@router.get("/api/agents/{agent}/runs")
async def agent_runs(agent: str, container: ContainerDep, version_id: str | None = None) -> list[AgentRun]:
    return await container.ledger.runs(agent=agent, version_id=version_id, limit=100)


@router.get("/api/agents/{agent}/scorecards")
async def scorecards(agent: str, container: ContainerDep) -> AgentScorecards:
    if agent not in SPECS:
        raise NotFoundError(f"agent {agent} not found")
    rubric = load_rubric(agent)
    safety = [criterion.id for criterion in rubric.criteria if criterion.safety]
    calibrations = await container.quality.calibrations(agent)
    versions = await container.versions.store.list(agent)
    serving = sorted(
        (v for v in versions if v.status in (VersionStatus.LIVE, VersionStatus.CANARY)),
        key=lambda v: v.status is not VersionStatus.LIVE,
    )
    others = [v for v in versions if v not in serving]
    cards: list[VersionCard] = []
    for version in [*serving, *others][:VERSIONS_SHOWN]:
        runs = await container.ledger.runs(version_id=version.version_id, finished=True, limit=1_000)
        reviews = await container.quality.store.reviews(version_id=version.version_id, limit=1_000)
        card = compute_scorecard(agent, version.version_id, runs, reviews, calibrations, safety)
        points = trend(agent, version.version_id, runs, reviews, calibrations, window=_window(runs), safety=safety)
        cards.append(VersionCard(version=version, scorecard=card, trend=points))
    decision = None
    pair = await container.canary.scorecards(agent)
    if pair is not None:
        decision = decide_canary(*pair, load_canary_config())
    return AgentScorecards(agent=agent, metrics=list(SCORECARD), versions=cards, canary=decision)


def _window(runs: list[AgentRun]) -> int:
    return max(MIN_WINDOW, math.ceil(len(runs) / TREND_POINTS))

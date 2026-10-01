from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field

from ahq.analytics import SimilarTicket, similar_tickets
from ahq.api.deps import ContainerDep, Operator
from ahq.config import load_world_config
from ahq.domain import StrictModel
from ahq.domain.world import KpiDimension, KpiMetric, KpiPoint
from ahq.retrieval import Audience, Namespace, SearchRequest, SearchResult

router = APIRouter(tags=["insight"])


class SearchQuery(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    audience: Audience = "customer"
    namespaces: list[Namespace] = Field(default_factory=list)
    as_of: date | None = Field(default=None, description="The day to search as of; the store's current day if null.")
    k: int = Field(default=5, ge=1, le=20)


class SimilarQuery(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    days: int = Field(default=30, ge=1, le=120)
    intent: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


async def store_day(container: ContainerDep) -> date:
    latest = await container.sim_runs.latest()
    world = load_world_config()
    return world.clock.day_at(latest.sim_now) if latest is not None else world.clock.day_at(world.anchor)


@router.get("/api/kpis")
async def kpis(
    container: ContainerDep,
    metric: KpiMetric,
    dimension: KpiDimension = "store",
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> list[KpiPoint]:
    return await container.world.kpis(metric, dimension, days=days)


@router.post("/api/retrieval/search")
async def search(body: SearchQuery, container: ContainerDep, operator: Operator) -> SearchResult:
    request = SearchRequest(
        query=body.query,
        as_of=body.as_of or await store_day(container),
        audience=body.audience,
        namespaces=tuple(body.namespaces),
        k=body.k,
    )
    return await container.retriever.search(request, trace=True)


@router.post("/api/analytics/similar-tickets")
async def find_similar_tickets(body: SimilarQuery, container: ContainerDep, operator: Operator) -> list[SimilarTicket]:
    if container.analytics is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "similar tickets need the Postgres database")
    until = datetime.combine(await store_day(container) + timedelta(days=1), time.min, tzinfo=UTC)
    return await similar_tickets(
        container.analytics,
        container.embedder,
        body.text,
        until - timedelta(days=body.days + 1),
        until,
        intent=body.intent,
        limit=body.limit,
    )

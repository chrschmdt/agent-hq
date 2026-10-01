from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from pydantic import BaseModel, Field

from ahq.analytics import RejectedSql, cluster_tickets, get_kpis, run_readonly_sql, similar_tickets
from ahq.domain import Effect, StrictModel, ToolResult
from ahq.domain.world import KpiDimension, KpiMetric
from ahq.ports import AnalyticsError
from ahq.tools.types import Invocation, ToolDeps, ToolSpec

MAX_OUTPUT_CHARS = 16_000
UNAVAILABLE = "Analytics is not available here: it needs the Postgres database."


class SqlQuery(StrictModel):
    sql: str = Field(
        description="One SELECT over schema-qualified tables in retail, support or kpi, such as retail.shipments."
    )


class KpiQuery(StrictModel):
    metric: KpiMetric
    dimension: KpiDimension = Field(description="store for the whole store, or category, carrier or region.")
    key: str | None = Field(default=None, description="One key of the dimension, such as northstar; all when null.")
    days: int = Field(default=14, ge=1, le=90, description="How many days back from today.")


class SimilarQuery(StrictModel):
    text: str = Field(min_length=1, description="What the tickets should be about, in plain words.")
    days: int = Field(default=30, ge=1, le=120)
    intent: str | None = Field(default=None, description="Only tickets with this intent, such as where_is_my_order.")
    limit: int = Field(default=10, ge=1, le=50)


class Window(StrictModel):
    days: int = Field(default=7, ge=1, le=120)


def _window(invocation: Invocation, deps: ToolDeps, days: int) -> tuple[datetime, datetime]:
    today = invocation.as_of(deps.clock)
    until = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC)
    return until - timedelta(days=days + 1), until


def _json(value: Any) -> str:
    text = json.dumps(value, default=str)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + " ... (cut off; narrow the query)"


async def _run_sql(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, SqlQuery)
    if deps.analytics is None:
        return ToolResult.error(UNAVAILABLE)
    try:
        rows = await run_readonly_sql(deps.analytics, args.sql)
    except (RejectedSql, AnalyticsError) as error:
        return ToolResult.error(str(error))
    return ToolResult(output=_json(rows.model_dump()))


async def _kpis(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, KpiQuery)
    if deps.analytics is None:
        return ToolResult.error(UNAVAILABLE)
    today: date = invocation.as_of(deps.clock)
    rows = await get_kpis(
        deps.analytics, args.metric, args.dimension, today - timedelta(days=args.days), today, key=args.key
    )
    return ToolResult(output=_json([row.model_dump(mode="json") for row in rows]))


async def _similar(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, SimilarQuery)
    if deps.analytics is None or deps.embedder is None:
        return ToolResult.error(UNAVAILABLE)
    since, until = _window(invocation, deps, args.days)
    found = await similar_tickets(
        deps.analytics, deps.embedder, args.text, since, until, intent=args.intent, limit=args.limit
    )
    return ToolResult(output=_json([ticket.model_dump(mode="json") for ticket in found]))


async def _clusters(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, Window)
    if deps.analytics is None:
        return ToolResult.error(UNAVAILABLE)
    since, until = _window(invocation, deps, args.days)
    clusters = await cluster_tickets(deps.analytics, since, until)
    return ToolResult(output=_json([cluster.model_dump() for cluster in clusters]))


async def _changes(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, Window)
    if deps.knowledge is None:
        return ToolResult.error("Change history is not available here.")
    today = invocation.as_of(deps.clock)
    versions = await deps.knowledge.versions_since(today - timedelta(days=args.days), today)
    return ToolResult(output=_json({"knowledge_base": [v.model_dump(mode="json") for v in versions]}))


def _tool(name: str, args: type[BaseModel], description: str, handler: Any) -> ToolSpec:
    return ToolSpec(
        name=name, server="analytics", effect=Effect.READ, description=description, args=args, handler=handler
    )


ANALYTICS_TOOLS: tuple[ToolSpec, ...] = (
    _tool(
        "analytics_get_kpis",
        KpiQuery,
        "Get daily values of one KPI, for the whole store or by category, carrier or region, over recent days. "
        "Metrics include orders, deliveries, late_delivery_rate, refund_rate, tickets and csat. Start here to see "
        "whether something moved, and when.",
        _kpis,
    ),
    _tool(
        "analytics_run_sql",
        SqlQuery,
        "Run one read-only SELECT against the store (retail), support tickets (support) and daily KPIs (kpi); "
        "tables must be schema-qualified. Results are capped at 200 rows. Use it to break a problem down, for "
        "example late shipments by carrier and region.",
        _run_sql,
    ),
    _tool(
        "analytics_similar_tickets",
        SimilarQuery,
        "Find past tickets whose opening message is close in meaning to a text, over recent days. Use it to see "
        "whether a complaint is part of a pattern, and to collect ticket ids as evidence.",
        _similar,
    ),
    _tool(
        "analytics_cluster_tickets",
        Window,
        "Group recent tickets by what they are about, largest group first, with example subjects and ticket ids. "
        "Use it to find recurring themes worth fixing.",
        _clusters,
    ),
    _tool(
        "analytics_recent_changes",
        Window,
        "List knowledge base articles and policy versions that took effect recently. Use it to check whether a "
        "problem started when something changed.",
        _changes,
    ),
)

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

ACTIVITY_TABLES = (
    "ops.events",
    "ops.approvals",
    "ops.work_items",
    "ops.sim_script",
    "ops.sim_runs",
    "agents.tool_calls_audit",
    "agents.proposals",
    "agents.incidents",
    "agents.kb_drafts",
    "agents.agent_runs",
    "agents.qa_labels",
    "agents.qa_reviews",
    "agents.eval_cases",
    "agents.eval_runs",
    "agents.spend_daily",
    "agents.model_health",
    "agents.provider_slots",
    "agents.agent_controls",
)
CHECKPOINT_TABLES = ("public.checkpoint_writes", "public.checkpoint_blobs", "public.checkpoints")
VERSION_TABLES = ("agents.agent_versions",)


async def activity_counts(engine: AsyncEngine, *, versions: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with engine.connect() as connection:
        for table in _tables(versions):
            if await connection.scalar(text("SELECT to_regclass(:name)"), {"name": table}) is None:
                continue
            counts[table] = int(await connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0)  # noqa: S608
    return counts


async def clear_activity(engine: AsyncEngine, *, versions: bool) -> dict[str, int]:
    counts = await activity_counts(engine, versions=versions)
    if counts:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE {', '.join(counts)}"))
    return counts


def _tables(versions: bool) -> tuple[str, ...]:
    return ACTIVITY_TABLES + CHECKPOINT_TABLES + (VERSION_TABLES if versions else ())


class PgActivityStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def clear(self, *, versions: bool) -> dict[str, int]:
        return await clear_activity(self._engine, versions=versions)

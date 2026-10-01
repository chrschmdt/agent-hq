from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from ahq.adapters.clock import WallClock
from ahq.adapters.mcp_client import InProcessToolProvider
from ahq.adapters.memory import MemoryEventLog
from ahq.db.checkpointer import open_checkpointer
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.migrate import upgrade
from ahq.db.repos import PgEventLog
from ahq.domain import new_work_item_id, thread_for
from ahq.graphs import SmokeDeps, build_smoke_graph
from ahq.mcp_servers import build_smoke_server
from ahq.settings import Settings
from ahq.testing import FakeChatModels
from tests.live.conftest import require

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]


def smoke_deps() -> SmokeDeps:
    clock = WallClock()
    return SmokeDeps(
        models=FakeChatModels(),
        tools=InProcessToolProvider({"smoke": {"agents": build_smoke_server(clock)}}),
        events=MemoryEventLog(),
        clock=clock,
    )


async def test_migrations_and_checkpoints_on_neon(live_settings: Settings) -> None:
    require(live_settings.database_url, "DATABASE_URL")
    require(live_settings.database_url_unpooled, "DATABASE_URL_UNPOOLED")
    assert live_settings.database_url is not None
    assert live_settings.database_url_unpooled is not None
    pooled = live_settings.database_url.get_secret_value()
    direct = live_settings.database_url_unpooled.get_secret_value()

    await asyncio.get_running_loop().run_in_executor(ThreadPoolExecutor(max_workers=1), upgrade, direct)

    engine = make_engine(pooled)
    try:
        assert await PgEventLog(make_sessionmaker(engine)).last_id() >= 0
    finally:
        await engine.dispose()

    work_item_id = new_work_item_id()
    config: RunnableConfig = {"configurable": {"thread_id": thread_for(work_item_id)}}
    async with open_checkpointer(pooled) as saver:
        graph = build_smoke_graph(smoke_deps()).compile(checkpointer=saver)
        paused = await graph.ainvoke({"work_item_id": work_item_id}, config, durability="sync", version="v2")
    async with open_checkpointer(pooled) as saver:
        graph = build_smoke_graph(smoke_deps()).compile(checkpointer=saver)
        resumed = await graph.ainvoke(
            Command(resume={paused.interrupts[0].id: {"verdict": "approve"}}), config, durability="sync", version="v2"
        )
    assert resumed.value["outcome"] == "approved"

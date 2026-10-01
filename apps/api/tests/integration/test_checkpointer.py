from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from ahq.adapters.clock import ManualClock
from ahq.adapters.mcp_client import InProcessToolProvider
from ahq.adapters.memory import MemoryEventLog
from ahq.db.checkpointer import open_checkpointer
from ahq.domain import new_work_item_id, thread_for
from ahq.graphs import SmokeDeps, build_smoke_graph
from ahq.mcp_servers import build_smoke_server
from ahq.testing import FakeChatModels

pytestmark = [pytest.mark.db, pytest.mark.pooled]


def graph_deps() -> SmokeDeps:
    clock = ManualClock()
    return SmokeDeps(
        models=FakeChatModels(),
        tools=InProcessToolProvider({"smoke": {"agents": build_smoke_server(clock)}}),
        events=MemoryEventLog(),
        clock=clock,
    )


async def test_an_approval_resumes_in_a_fresh_process_through_pgbouncer(pooled_pg_url: str) -> None:
    work_item_id = new_work_item_id()
    config: RunnableConfig = {"configurable": {"thread_id": thread_for(work_item_id)}}

    async with open_checkpointer(pooled_pg_url) as first_process:
        graph = build_smoke_graph(graph_deps()).compile(checkpointer=first_process)
        paused = await graph.ainvoke({"work_item_id": work_item_id}, config, durability="sync", version="v2")
    interrupt_id = paused.interrupts[0].id

    async with open_checkpointer(pooled_pg_url) as second_process:
        graph = build_smoke_graph(graph_deps()).compile(checkpointer=second_process)
        snapshot = await graph.aget_state(config)
        assert [pending.id for pending in snapshot.interrupts] == [interrupt_id]
        resumed = await graph.ainvoke(
            Command(resume={interrupt_id: {"approval_id": "apv_1", "decision": {"verdict": "approve"}}}),
            config,
            durability="sync",
            version="v2",
        )

    assert resumed.value["outcome"] == "approved"
    assert resumed.interrupts == ()

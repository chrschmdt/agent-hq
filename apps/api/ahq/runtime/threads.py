from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from langgraph.types import StateSnapshot

from ahq.domain import WorkItemId, WorkKind
from ahq.graphs import TeamState, ThreadView, thread_view
from ahq.ports import WorkStore
from ahq.runtime.registry import GraphRegistry

TEAM_KINDS = frozenset({WorkKind.TICKET, WorkKind.ALERT, WorkKind.FLAG})


@dataclass(frozen=True)
class Threads:
    work: WorkStore
    graphs: GraphRegistry

    async def view(self, work_item_id: str) -> ThreadView | None:
        item = await self.work.get(WorkItemId(work_item_id))
        if item.kind not in TEAM_KINDS:
            return None
        config: Any = {"configurable": {"thread_id": item.thread_id}}
        snapshot = await self.graphs.graph(item.kind).aget_state(config, subgraphs=True)
        if not snapshot.values:
            return None
        values = dict(snapshot.values)
        for task in snapshot.tasks:
            if isinstance(task.state, StateSnapshot) and task.state.values:
                values.update(task.state.values)
        return thread_view(cast("TeamState", values))

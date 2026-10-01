from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from ahq.domain import WorkItem, WorkKind, WorkStatus
from ahq.ports import TraceKind


def _done(value: Any) -> WorkStatus:
    return WorkStatus.DONE


def fixed_input(make: Callable[[WorkItem], dict[str, Any]]) -> Callable[[WorkItem], Awaitable[dict[str, Any]]]:
    async def initial(item: WorkItem) -> dict[str, Any]:
        return make(item)

    return initial


@dataclass(frozen=True)
class GraphSpec:
    build: Callable[[], StateGraph[Any]]
    initial_input: Callable[[WorkItem], Awaitable[dict[str, Any]]]
    run_name: str
    trace_kind: TraceKind = TraceKind.ROUTINE
    message_input: Callable[[WorkItem, int], Awaitable[dict[str, Any]]] | None = None
    message_key: str | None = None
    finished_status: Callable[[Any], WorkStatus] = _done


class GraphRegistry:
    def __init__(self, specs: Mapping[WorkKind, GraphSpec], checkpointer: BaseCheckpointSaver[Any]) -> None:
        self._specs = dict(specs)
        self._checkpointer = checkpointer
        self._compiled: dict[WorkKind, CompiledStateGraph[Any]] = {}

    def spec(self, kind: WorkKind) -> GraphSpec:
        return self._specs[kind]

    def graph(self, kind: WorkKind) -> CompiledStateGraph[Any]:
        if kind not in self._compiled:
            self._compiled[kind] = self._specs[kind].build().compile(checkpointer=self._checkpointer)
        return self._compiled[kind]

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph.state import CompiledStateGraph

from ahq.domain import StrictModel
from ahq.graphs.agent import build_agent_graph
from ahq.graphs.deps import TeamDeps
from ahq.graphs.team import build_team_graph


def _unused_deps() -> TeamDeps:
    unused: Any = None
    return TeamDeps(
        models=unused, tools=unused, gate=unused, tickets=unused, events=unused, clock=unused, context_key=""
    )


class TopologyNode(StrictModel):
    id: str
    kind: Literal["start", "end", "agent", "step"]


class TopologyEdge(StrictModel):
    source: str
    target: str
    conditional: bool


class Topology(StrictModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


AGENT_NODES = frozenset({"support", "ops", "insights"})


def _topology(graph: CompiledStateGraph[Any]) -> Topology:
    drawn = graph.get_graph()
    kinds: dict[str, Literal["start", "end", "agent", "step"]] = {"__start__": "start", "__end__": "end"}
    nodes = [
        TopologyNode(id=node_id, kind=kinds.get(node_id, "agent" if node_id in AGENT_NODES else "step"))
        for node_id in drawn.nodes
    ]
    edges = [TopologyEdge(source=edge.source, target=edge.target, conditional=edge.conditional) for edge in drawn.edges]
    return Topology(nodes=nodes, edges=edges)


def team_topology() -> Topology:
    return _topology(build_team_graph(_unused_deps()).compile())


def agent_loop_topology() -> Topology:
    return _topology(build_agent_graph("support", _unused_deps()).compile())

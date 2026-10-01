from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from ahq.agents.dispatcher import DISPATCHER
from ahq.agents.insights import INSIGHTS
from ahq.agents.ops import OPS
from ahq.agents.support import SUPPORT
from ahq.agents.types import AgentSpec, SpecProblem
from ahq.domain import Effect
from ahq.tools import EFFECTS_AT, Principal, ToolSpec

SPECS: Mapping[str, AgentSpec] = MappingProxyType({spec.name: spec for spec in (DISPATCHER, SUPPORT, OPS, INSIGHTS)})
CONTEXT_VALUES = frozenset({"today", "now", "ticket_id", "work_item_id"})


def load_spec(name: str) -> AgentSpec:
    return SPECS[name]


def principal_for(spec: AgentSpec) -> Principal:
    return Principal(
        subject=spec.name,
        autonomy=spec.autonomy,
        tools=frozenset(spec.tools),
        customer_scoped=spec.customer_scoped,
        audience=spec.audience,
    )


def validate_spec(spec: AgentSpec, catalog: Mapping[str, ToolSpec]) -> list[SpecProblem]:
    problems: list[SpecProblem] = []

    def problem(text: str) -> None:
        problems.append(SpecProblem(spec=spec.version_id, problem=text))

    for name in spec.tools:
        if name not in catalog:
            problem(f"unknown tool {name}")
        elif catalog[name].effect not in EFFECTS_AT[spec.autonomy]:
            problem(f"{name} needs more autonomy than {spec.autonomy.name}")
    writes = [name for name in spec.tools if name in catalog and catalog[name].effect is Effect.WRITE]
    if writes and not spec.customer_scoped:
        problem("an agent that changes accounts must be scoped to one customer")
    if spec.prompt.placeholders - CONTEXT_VALUES:
        problem(f"unexpected prompt placeholders {sorted(spec.prompt.placeholders - CONTEXT_VALUES)}")
    if spec.checks_citations and ("knowledge_search" not in spec.tools or "citations" not in spec.reply.model_fields):
        problem("checking citations needs knowledge_search and a reply with citations")
    return problems


def all_problems(specs: Iterable[AgentSpec], catalog: Mapping[str, ToolSpec]) -> list[SpecProblem]:
    return [problem for spec in specs for problem in validate_spec(spec, catalog)]

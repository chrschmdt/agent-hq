from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Response
from pydantic import Field, JsonValue

from ahq.agents import SPECS
from ahq.api.deps import ContainerDep
from ahq.config import ModelRole
from ahq.domain import Event, EventKind, NotFoundError, StrictModel, WorkItem
from ahq.graphs import Topology, agent_loop_topology, team_topology
from ahq.management import LimitsView
from ahq.tools import CATALOG, ToolSpec

router = APIRouter(tags=["agents"])

ROLES: tuple[ModelRole, ...] = ("guard", "dispatcher", "support", "ops", "insights", "qa", "customer")
ACTIVITY = frozenset({EventKind.MODEL_CALLED, EventKind.TOOL_CALLED, EventKind.AGENT_HANDOFF, EventKind.WORK_ROUTED})


class GraphTopology(StrictModel):
    team: Topology
    agent_loop: Topology


class ToolInfo(StrictModel):
    name: str
    server: str
    effect: str
    description: str
    customer_scoped: bool
    refund_gated: bool
    exception: bool = Field(default=False, description="An exception to policy: every call waits for a person.")
    parameters: dict[str, JsonValue] = Field(description="The JSON schema of the tool's arguments.")


class LineupModel(StrictModel):
    key: str
    id: str
    provider: str
    reasoning: bool


class Lineup(StrictModel):
    profile: str
    roles: dict[str, LineupModel]
    embeddings: str
    rerank: str


class CanarySummary(StrictModel):
    version_id: str
    pct: int
    since: datetime


class AgentSummary(StrictModel):
    name: str
    version: str
    role: str
    model: str
    model_id: str
    autonomy: str
    audience: str
    customer_scoped: bool
    can_flag: bool
    tools: list[str]
    max_model_calls: int
    max_usd: float
    answer: str
    work: dict[str, int] = Field(description="Work items it owns, by status.")
    canary: CanarySummary | None = None
    paused: bool = False
    pause_reason: str | None = None


class AgentDetail(AgentSummary):
    prompt_stable: str
    prompt_context: str
    prompt_digest: str
    answer_schema: dict[str, JsonValue]
    tool_details: list[ToolInfo]
    models_by_profile: dict[str, str]
    recent_events: list[Event]
    recent_work: list[WorkItem]
    version_model: str | None = Field(description="The model the live version names, if it names one.")
    granted_tools: list[str]
    model_choices: list[str]


@router.get("/api/graph")
async def graph_topology() -> GraphTopology:
    return GraphTopology(team=team_topology(), agent_loop=agent_loop_topology())


@router.get("/api/lineup")
async def lineup(container: ContainerDep) -> Lineup:
    await container.model_switch.refresh()
    catalog = container.catalog
    roles: dict[str, LineupModel] = {}
    for role in ROLES:
        key = container.models.model_key(role)
        model = catalog.models[key]
        provider = model.id.split("/", 1)[0] if "/" in model.id else model.route
        roles[role] = LineupModel(key=key, id=model.id, provider=provider, reasoning=model.reasoning is not None)
    return Lineup(
        profile=container.model_switch.current,
        roles=roles,
        embeddings=catalog.embeddings.id,
        rerank=catalog.rerank.id,
    )


@router.get("/api/agents")
async def list_agents(container: ContainerDep) -> list[AgentSummary]:
    await container.model_switch.refresh()
    limits = await container.limiter.view(list(SPECS))
    return [await _summary(name, container, limits) for name in SPECS]


@router.get("/api/agents/{name}")
async def get_agent(name: str, container: ContainerDep) -> AgentDetail:
    if name not in SPECS:
        raise NotFoundError(f"agent {name} not found")
    await container.model_switch.refresh()
    summary = await _summary(name, container, await container.limiter.view([name]))
    spec = await container.versions.spec(summary.version)
    catalog = container.catalog
    return AgentDetail(
        **summary.model_dump(),
        prompt_stable=spec.prompt.stable,
        prompt_context=spec.prompt.context,
        prompt_digest=spec.prompt.digest,
        answer_schema=spec.reply.model_json_schema(),
        tool_details=[_tool(CATALOG[tool]) for tool in spec.tools if tool in CATALOG],
        models_by_profile={profile: catalog.resolve(profile, spec.role, spec.model)[0] for profile in catalog.profiles},
        recent_events=await container.events.recent(kinds=ACTIVITY, actor=name, limit=50),
        recent_work=await container.work.list(owner=name, limit=20),
        version_model=spec.model,
        granted_tools=list(SPECS[name].tools),
        model_choices=sorted(key for key, model in catalog.models.items() if model.route != "fake"),
    )


CATALOG_CACHE = "public, max-age=3600, s-maxage=86400"


@router.get("/api/tools")
async def list_tools(response: Response) -> list[ToolInfo]:
    response.headers["Cache-Control"] = CATALOG_CACHE
    return [_tool(tool) for tool in CATALOG.values()]


@router.get("/api/tools/{name}")
async def get_tool(name: str, response: Response) -> ToolInfo:
    tool = CATALOG.get(name)
    if tool is None:
        raise NotFoundError(f"tool {name} not found")
    response.headers["Cache-Control"] = CATALOG_CACHE
    return _tool(tool)


async def _summary(name: str, container: ContainerDep, limits: LimitsView) -> AgentSummary:
    serving = await container.versions.serving(name)
    spec = await container.versions.spec(serving.live.version_id) if serving.live else SPECS[name]
    catalog = container.catalog
    model, _ = catalog.resolve(container.model_switch.current, spec.role, spec.model)
    work: dict[str, int] = {}
    for item in await container.work.list(owner=name, limit=500):
        work[item.status.value] = work.get(item.status.value, 0) + 1
    mine = next((row for row in limits.agents if row.agent == name), None)
    canary = serving.canary
    return AgentSummary(
        name=spec.name,
        version=spec.version_id,
        role=spec.role,
        model=model,
        model_id=catalog.models[model].id,
        autonomy=spec.autonomy.name.lower(),
        audience=spec.audience,
        customer_scoped=spec.customer_scoped,
        can_flag=spec.can_flag,
        tools=list(spec.tools),
        max_model_calls=spec.limits.max_model_calls,
        max_usd=spec.limits.max_usd,
        answer=spec.reply.__name__,
        work=work,
        canary=CanarySummary(version_id=canary.version_id, pct=canary.canary_pct or 0, since=canary.status_at)
        if canary
        else None,
        paused=mine.paused if mine else False,
        pause_reason=mine.reason if mine else None,
    )


def _tool(tool: ToolSpec) -> ToolInfo:
    function = tool.model_schema()["function"]
    assert isinstance(function, dict)
    parameters = function["parameters"]
    assert isinstance(parameters, dict)
    return ToolInfo(
        name=tool.name,
        server=tool.server,
        effect=tool.effect.value,
        description=tool.description,
        customer_scoped=tool.customer_scoped,
        refund_gated=tool.refund_gated,
        exception=tool.exception,
        parameters=parameters,
    )

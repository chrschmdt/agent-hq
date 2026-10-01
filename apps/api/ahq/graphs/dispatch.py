from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ahq.agents import AgentSpec
from ahq.domain import CallReport, Route, RouteDecision
from ahq.graphs.state import WorkKindName
from ahq.ports import ChatModels, ask_typed

ALLOWED_ROUTES: dict[WorkKindName, tuple[Route, ...]] = {
    "ticket": ("support", "human"),
    "alert": ("ops", "human"),
    "flag": ("ops", "insights", "human"),
}
DEFAULT_ROUTE: dict[WorkKindName, Route] = {"ticket": "support", "alert": "ops", "flag": "ops"}
UNREADABLE = "The dispatcher's answer could not be read, so the work went to its default owner."


def work_message(kind: WorkKindName, brief: str) -> str:
    return f"Kind of work: {kind}\n\n{brief}"


async def decide_route(
    models: ChatModels, spec: AgentSpec, kind: WorkKindName, brief: str, today: str, *, model: str | None = None
) -> tuple[RouteDecision, CallReport | None]:
    system = spec.prompt.render({"today": today})
    messages = [SystemMessage(system.text), HumanMessage(work_message(kind, brief))]
    try:
        decision, report = await ask_typed(models, spec.role, RouteDecision, messages, model=model)
    except ValueError:
        fallback = RouteDecision(route=DEFAULT_ROUTE[kind], priority="normal", reason=UNREADABLE, split=[])
        return fallback, None
    if decision.route not in ALLOWED_ROUTES[kind]:
        reason = f"{kind} work cannot go to {decision.route}, so it went to its default owner. {decision.reason}"
        decision = decision.model_copy(update={"route": DEFAULT_ROUTE[kind], "reason": reason})
    return decision, report


def default_route(kind: WorkKindName, reason: str) -> RouteDecision:
    return RouteDecision(route=DEFAULT_ROUTE[kind], priority="normal", reason=reason, split=[])

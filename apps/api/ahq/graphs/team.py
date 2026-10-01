from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import JsonValue

from ahq.config import ModelRole
from ahq.domain import CallReport, EventKind, NewEvent, Screening, SupportTurn, WorkItemId
from ahq.domain.world import TicketMessage, TicketStatus
from ahq.graphs.agent import HANDOFF_REPLY, build_agent_graph
from ahq.graphs.deps import TeamDeps
from ahq.graphs.dispatch import decide_route, default_route
from ahq.graphs.ledger import Totals, charged, opened, runs_of
from ahq.graphs.state import PER_TURN, Disposition, TeamState, TeamUpdate
from ahq.graphs.tickets import customer_messages
from ahq.guardrails import assess_threat, joined, screening_of

type Owner = Literal["support", "ops", "insights", "human"]
type Entry = Literal["dispatcher", "support", "ops", "insights", "human"]
OWNERS: tuple[Owner, ...] = ("support", "ops", "insights", "human")
DISPATCHER = "dispatcher"
GUARD = "guard"
BRIEF = "brief"

TICKET_STATUS: dict[Disposition, TicketStatus] = {
    "waiting_customer": "waiting_customer",
    "done": "resolved",
    "escalated": "escalated",
}


def disposition_of(state: TeamState) -> Disposition:
    if state.get("escalated"):
        return "escalated"
    if state["kind"] != "ticket":
        return "done"
    turn = SupportTurn.model_validate(state.get("outputs", {})["support"])
    return "done" if turn.status == "resolved" else "waiting_customer"


def route_entry(state: TeamState) -> Entry:
    match state.get("owner"):
        case "support" | "ops" | "insights" | "human" as owner:
            return owner
        case _:
            return "dispatcher"


def unscreened(state: TeamState) -> tuple[list[str], list[str]]:
    seen = set(state.get("screened", []))
    if state["kind"] == "alert":
        return [], []
    if state["kind"] == "flag":
        return ([], []) if BRIEF in seen else ([state.get("brief", "")], [BRIEF])
    messages = [m for m in customer_messages(state.get("support_messages", [])) if m.id not in seen]
    texts = [str(m.text) for m in messages]
    ids = [str(m.id) for m in messages]
    if BRIEF not in seen:
        texts = [state.get("brief", ""), *texts[1:]]
        ids.append(BRIEF)
    return texts, ids


def build_team_graph(deps: TeamDeps) -> StateGraph[TeamState]:
    async def emit(state: TeamState, kind: EventKind, payload: dict[str, JsonValue], actor: str) -> None:
        event = NewEvent(
            kind=kind,
            occurred_at=deps.clock.now(),
            work_item_id=WorkItemId(state["work_item_id"]),
            actor=actor,
            payload=payload,
        )
        await deps.events.append([event])

    def entry(state: TeamState) -> TeamUpdate:
        return {**PER_TURN}

    async def screen(state: TeamState) -> Command[Entry]:
        goto = route_entry(state)
        texts, ids = unscreened(state)
        if deps.screen is None or goto == "human" or not ids:
            return Command(goto=goto)
        update: TeamUpdate = {"screened": [*state.get("screened", []), *ids]}
        text = joined(texts)
        screening = deps.screen.match(text) if text else None
        if screening is None and text and deps.screen.classifier:
            screening = await classify(state, text)
        if screening is None:
            return Command(goto=goto, update=update)
        update["screening"] = screening.model_dump()
        if not screening.blocked:
            return Command(goto=goto, update=update)
        await emit(state, EventKind.GUARDRAIL_BLOCKED, {"stage": "input", **screening.model_dump()}, GUARD)
        return Command(goto="human", update=update)

    async def classify(state: TeamState, text: str) -> Screening | None:
        model = deps.models.model_key(GUARD)
        allowed = await deps.limits.before_call(GUARD, model)
        if allowed.verdict in ("pause", "deny"):
            return None
        model = allowed.model
        started = deps.clock.now()
        try:
            assessment, report = await assess_threat(deps.models, text, model=model)
        except ValueError:
            await deps.limits.after_call(GUARD, model, cost_usd=0.0, ok=True)
            return None
        except Exception as error:
            await deps.limits.after_call(GUARD, model, cost_usd=0.0, ok=False, error=repr(error))
            raise
        seconds = (deps.clock.now() - started).total_seconds()
        screening = screening_of(assessment)
        verdict: dict[str, JsonValue] = {"screening": screening.model_dump(mode="json")}
        cost = await record_call(state, GUARD, GUARD, None, model, report, seconds, verdict)
        await deps.limits.after_call(GUARD, model, cost_usd=cost, ok=True)
        return screening

    async def dispatch(state: TeamState) -> Command[Owner]:
        spec = await deps.agents.pin(DISPATCHER, state["work_item_id"])
        entry = Totals(**{**opened(spec.version_id, deps.clock.now()), "turns": 1})
        kind = state["kind"]
        model = deps.models.model_key(spec.role, spec.model)
        allowed = await deps.limits.before_call(DISPATCHER, model)
        if allowed.verdict in ("pause", "deny"):
            why = "is paused" if allowed.verdict == "pause" else "has spent its daily budget"
            decision = default_route(kind, f"The Dispatcher {why}, so the work went to its default owner.")
        else:
            model = allowed.model
            started = deps.clock.now()
            try:
                decision, report = await decide_route(
                    deps.models, spec, kind, state.get("brief", ""), state["today"], model=model
                )
            except Exception as error:
                await deps.limits.after_call(DISPATCHER, model, cost_usd=0.0, ok=False, error=repr(error))
                raise
            seconds = (deps.clock.now() - started).total_seconds()
            cost = await record_call(state, DISPATCHER, "dispatcher", spec.version_id, model, report, seconds)
            await deps.limits.after_call(DISPATCHER, model, cost_usd=cost, ok=True)
            entry = charged(entry, report, cost, seconds)
        paused = await deps.limits.paused()
        if decision.route in paused:
            reason = f"{decision.route} is paused, so a person takes the work. {decision.reason}"
            decision = decision.model_copy(update={"route": "human", "reason": reason})
        await emit(state, EventKind.WORK_ROUTED, decision.model_dump(mode="json"), DISPATCHER)
        update: TeamUpdate = {
            "route": decision.model_dump(mode="json"),
            "owner": decision.route,
            "versions": {DISPATCHER: spec.version_id},
            "ledger": {DISPATCHER: dict(entry)},
        }
        return Command(goto=decision.route, update=update)

    async def record_call(
        state: TeamState,
        actor: str,
        role: ModelRole,
        version_id: str | None,
        model: str,
        report: CallReport | None,
        seconds: float,
        extra: dict[str, JsonValue] | None = None,
    ) -> float:
        if report is None:
            return 0.0
        cost = report.cost_usd(deps.models.price(role, model))
        payload: dict[str, JsonValue] = {
            "agent": actor,
            "version": version_id,
            "model": model,
            "provider": report.provider,
            "usage": report.usage.model_dump(),
            "cost_usd": cost,
            "seconds": round(seconds, 3),
            **(extra or {}),
        }
        await emit(state, EventKind.MODEL_CALLED, payload, actor)
        return cost

    def human(state: TeamState) -> TeamUpdate:
        update: TeamUpdate = {"escalated": True, "owner": "human"}
        if state["kind"] == "ticket" and "support" not in state.get("outputs", {}):
            screening = state.get("screening")
            if screening is not None and screening["blocked"]:
                summary = f"The input check held this for a person ({screening['threat']}): {screening['reason']}"
            else:
                summary = (state.get("route") or {}).get("reason", "Needs a person.")
            turn = SupportTurn(reply=HANDOFF_REPLY, citations=[], status="transferred", summary=summary)
            update["outputs"] = {**state.get("outputs", {}), "support": turn.model_dump()}
        return update

    async def finalize(state: TeamState) -> TeamUpdate:
        disposition = disposition_of(state)
        if state["kind"] == "ticket":
            await record_reply(state, disposition)
        if deps.after_run is not None:
            await deps.after_run(runs_of(state, disposition, deps.clock.now()))
        return {"disposition": disposition}

    async def record_reply(state: TeamState, disposition: Disposition) -> None:
        turn = SupportTurn.model_validate(state.get("outputs", {})["support"])
        simulated = await deps.store_time(state["work_item_id"]) if deps.store_time is not None else None
        now = simulated or deps.clock.now()
        ticket_id = state.get("ticket_id", "")
        await deps.tickets.add_message(
            ticket_id, state.get("reply_position", 0), TicketMessage(author="agent", body=turn.reply, created_at=now)
        )
        closed = disposition != "waiting_customer"
        await deps.tickets.set_status(ticket_id, TICKET_STATUS[disposition], resolved_at=now if closed else None)
        replied: dict[str, Any] = {
            "ticket_id": ticket_id,
            "reply": turn.reply,
            "citations": list(turn.citations),
            "status": turn.status,
            "summary": turn.summary,
            "citation_problems": state.get("citation_problems", []),
        }
        await emit(state, EventKind.TICKET_REPLIED, replied, "support")
        if closed:
            outcome: dict[str, Any] = {
                "ticket_id": ticket_id,
                "outcome": disposition,
                "writes": state.get("writes", []),
                "stop_reason": state.get("stop_reason"),
            }
            await emit(state, EventKind.TICKET_CLOSED, outcome, "support")
        if deps.after_reply is not None:
            await deps.after_reply(state["work_item_id"], state.get("reply_position", 0), not closed)

    graph = StateGraph(TeamState)
    graph.add_node("entry", entry)
    graph.add_node("screen", screen, destinations=(DISPATCHER, *OWNERS))
    graph.add_node("dispatcher", dispatch, destinations=OWNERS)
    graph.add_node("support", build_agent_graph("support", deps).compile(), destinations=("human", "finalize"))
    graph.add_node("ops", build_agent_graph("ops", deps).compile(), destinations=("insights", "human", "finalize"))
    graph.add_node("insights", build_agent_graph("insights", deps).compile(), destinations=("human", "finalize"))
    graph.add_node("human", human)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "entry")
    graph.add_edge("entry", "screen")
    graph.add_edge("human", "finalize")
    graph.add_edge("finalize", END)
    return graph

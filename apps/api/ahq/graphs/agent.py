from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.graph import START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, JsonValue, ValidationError

from ahq.agents import AgentSpec, principal_for
from ahq.domain import (
    FLAG_TOOL,
    ApprovalRequest,
    ApprovalResume,
    CallReport,
    Effect,
    EventKind,
    NewEvent,
    PatternFlag,
    SupportTurn,
    ToolResult,
    WorkItemId,
    thread_for,
)
from ahq.graphs.deps import TeamDeps
from ahq.graphs.ledger import Totals, charged, opened, totals
from ahq.graphs.outcomes import Conclusion, conclude
from ahq.graphs.state import CHANNELS, PER_AGENT, TeamState, TeamUpdate
from ahq.graphs.tickets import customer_messages
from ahq.ports import REPLY_TOOL, ask_typed
from ahq.retrieval import check_citations
from ahq.tools import (
    CATALOG,
    CONTEXT_ARG,
    Allow,
    CallContext,
    Deny,
    Principal,
    ReadCache,
    encode_context,
    exposed_tools,
    summarize_result,
)
from ahq.tools.types import ToolSpec

HANDOFF_REPLY = "I'm passing your request to a colleague, who will follow up with you shortly."
CONTEXT_TTL = timedelta(minutes=10)
IDENTITY_TOOLS = frozenset({"find_user_id_by_email", "find_user_id_by_name_zip"})
KNOWLEDGE_TOOLS = frozenset({"knowledge_search", "knowledge_get_article"})
DRAFT_TOOL = "knowledge_draft_article"
TRANSFER_TOOL = "transfer_to_human_agents"
REPAIR = "Rewrite the assistant's last message as the JSON object the instructions ask for, and nothing else."
CITATION_CHECK = (
    "Automatic check, not from the customer: these citations are not passages you received that are in effect "
    "today: {ids}. Search again if you need to, then send your reply again, citing only passages you received."
)
FLAG_SCHEMA: dict[str, JsonValue] = {
    "type": "function",
    "function": {
        "name": FLAG_TOOL,
        "description": (
            "Tell the operations team about a problem that looks bigger than this customer, such as a parcel days "
            "late with a carrier, a product fault, or a policy that confuses customers. The team looks into it "
            "separately; this does not change anything for the customer."
        ),
        "parameters": {
            key: value for key, value in PatternFlag.model_json_schema().items() if key not in {"title", "description"}
        },
    },
}
NO_FLAGS = "Flagging is not available here."
STOPPED_BECAUSE = {
    "max_model_calls": "it reached its limit on model calls",
    "budget": "it reached its spending limit for this work",
    "daily_budget": "the daily budget is spent",
    "paused": "an operator paused it",
    "unreadable": "it gave an answer that could not be read",
    "reply_blocked": "the reply check held back its reply",
}


@dataclass(frozen=True)
class Kit:
    spec: AgentSpec
    principal: Principal
    tools: dict[str, ToolSpec]
    schemas: list[dict[str, JsonValue]]

    @classmethod
    def of(cls, spec: AgentSpec) -> Kit:
        principal = principal_for(spec)
        tools = {tool.name: tool for tool in exposed_tools(principal, CATALOG.values())}
        schemas = [tool.model_schema() for tool in tools.values()] + ([FLAG_SCHEMA] if spec.can_flag else [])
        return cls(spec=spec, principal=principal, tools=tools, schemas=schemas)


def build_agent_graph(name: str, deps: TeamDeps) -> StateGraph[TeamState]:
    channel = CHANNELS[name]
    kits: dict[str, Kit] = {}

    async def kit(state: TeamState) -> Kit:
        version_id = state.get("versions", {})[name]
        if version_id not in kits:
            kits[version_id] = Kit.of(await deps.agents.spec(version_id))
        return kits[version_id]

    def context(
        state: TeamState, principal: Principal, tool_call_id: str, approval_id: str | None = None
    ) -> CallContext:
        return CallContext(
            work_item_id=state["work_item_id"],
            thread_id=thread_for(WorkItemId(state["work_item_id"])),
            tool_call_id=tool_call_id,
            subject=principal.subject,
            verified_customer_id=state.get("verified_customer_id"),
            approval_id=approval_id,
            as_of=date.fromisoformat(state["today"]),
            expires_at=deps.clock.now() + CONTEXT_TTL,
        )

    async def emit(state: TeamState, kind: EventKind, payload: dict[str, JsonValue]) -> None:
        event = NewEvent(
            kind=kind,
            occurred_at=deps.clock.now(),
            work_item_id=WorkItemId(state["work_item_id"]),
            actor=name,
            payload=payload,
        )
        await deps.events.append([event])

    async def record_report(
        state: TeamState,
        spec: AgentSpec,
        model: str,
        report: CallReport,
        seconds: float,
        call: dict[str, JsonValue],
    ) -> float:
        cost = report.cost_usd(deps.models.price(spec.role, model))
        await emit(
            state,
            EventKind.MODEL_CALLED,
            {
                "agent": name,
                "version": spec.version_id,
                "model": model,
                "provider": report.provider,
                "usage": report.usage.model_dump(),
                "cost_usd": cost,
                "seconds": round(seconds, 3),
                **call,
            },
        )
        return cost

    def ledger(entry: Totals) -> dict[str, Any]:
        return {name: dict(entry)}

    async def begin(state: TeamState) -> TeamUpdate:
        update: TeamUpdate = {**PER_AGENT}
        version_id = state.get("versions", {}).get(name)
        if version_id is None:
            version_id = (await deps.agents.pin(name, state["work_item_id"])).version_id
            update["versions"] = {name: version_id}
        entry = totals(state, name) if name in state.get("ledger", {}) else opened(version_id, deps.clock.now())
        update["ledger"] = ledger(Totals(**{**entry, "turns": entry["turns"] + 1, "stop_reason": None}))
        if not state.get(channel):
            update[channel] = [HumanMessage(state.get("brief", ""), id=f"{state['work_item_id']}:brief")]
        return update

    async def call_model(state: TeamState) -> TeamUpdate:
        spec = (await kit(state)).spec
        entry = totals(state, name)
        if state.get("model_calls", 0) >= spec.limits.max_model_calls:
            return {"stop_reason": "max_model_calls"}
        if entry["cost_usd"] >= spec.limits.max_usd:
            return {"stop_reason": "budget"}
        model = deps.models.model_key(spec.role, spec.model)
        decision = await deps.limits.before_call(name, model)
        if decision.verdict == "pause":
            return {"stop_reason": "paused"}
        if decision.verdict == "deny":
            return {"stop_reason": "daily_budget"}
        model = decision.model
        system = spec.prompt.render(
            {
                "today": state["today"],
                "now": state.get("now", state["today"]),
                "ticket_id": state.get("ticket_id", "none"),
                "work_item_id": state["work_item_id"],
            }
        )
        runnable = deps.models.agent_model(
            spec.role, model=model, system=system, tools=(await kit(state)).schemas, reply=spec.reply
        )
        started = deps.clock.now()
        try:
            message = await runnable.ainvoke(state.get(channel, []))
        except Exception as error:
            await deps.limits.after_call(name, model, cost_usd=0.0, ok=False, error=repr(error))
            raise
        assert isinstance(message, AIMessage)
        seconds = (deps.clock.now() - started).total_seconds()
        report = deps.models.report(message)
        passes = entry["model_calls"] + 1
        if message.id is None:
            message = message.model_copy(update={"id": f"{state['work_item_id']}:{name}:{passes}"})
        asked: list[JsonValue] = [{"id": call_id(call), "name": call["name"]} for call in message.tool_calls]
        called: dict[str, JsonValue] = {"pass": passes, "message_id": message.id, "tools": asked}
        cost = await record_report(state, spec, model, report, seconds, called)
        await deps.limits.after_call(name, model, cost_usd=cost, ok=True)
        update: TeamUpdate = {
            "model_calls": state.get("model_calls", 0) + 1,
            "ledger": ledger(charged(entry, report, cost, seconds)),
        }
        update[channel] = [message]
        return update

    def after_model(state: TeamState) -> Literal["authorize", "emit_output", "give_up"]:
        if state.get("stop_reason"):
            return "give_up"
        calls = last_ai(state.get(channel, [])).tool_calls
        return "authorize" if calls and not _replied(calls) else "emit_output"

    def pending_calls(state: TeamState) -> list[ToolCall]:
        return list(last_ai(state.get(channel, [])).tool_calls)

    async def authorize(state: TeamState) -> TeamUpdate:
        current = await kit(state)
        decisions: dict[str, dict[str, Any]] = {}
        for call in pending_calls(state):
            if current.spec.can_flag and call["name"] == FLAG_TOOL:
                decisions[call_id(call)] = Allow().model_dump()
                continue
            principal = current.principal
            ctx = context(state, principal, call_id(call))
            decisions[call_id(call)] = (await deps.gate.assess(principal, call["name"], call["args"], ctx)).model_dump()
        return {"decisions": decisions, "grants": {}, "edits": {}}

    def after_authorize(state: TeamState) -> Literal["approval_gate", "execute_tools"]:
        waiting = any(d["verdict"] == "approval" for d in state.get("decisions", {}).values())
        return "approval_gate" if waiting else "execute_tools"

    async def approval_gate(state: TeamState) -> TeamUpdate:
        tools = (await kit(state)).tools
        decisions = dict(state.get("decisions", {}))
        grants = dict(state.get("grants", {}))
        edits = dict(state.get("edits", {}))
        call = next(c for c in pending_calls(state) if decisions[call_id(c)]["verdict"] == "approval")
        decision = decisions[call_id(call)]
        request = ApprovalRequest(
            action=call["name"],
            arguments=call["args"],
            reason=decision["reason"],
            cost_usd=decision["refund_usd"],
            evidence=[f"ticket {state.get('ticket_id')}", f"customer {state.get('verified_customer_id')}"],
        )
        answer = interrupt(request.model_dump(mode="json"), response_schema=ApprovalResume)
        decisions[call_id(call)] = _apply(answer, tools[call["name"]], call, grants, edits)
        entry = totals(state, name)
        rejected = int(answer.decision.verdict == "reject")
        counted = Totals(
            **{
                **entry,
                "approvals": entry["approvals"] + 1,
                "rejected_approvals": entry["rejected_approvals"] + rejected,
            }
        )
        return {"decisions": decisions, "grants": grants, "edits": edits, "ledger": ledger(counted)}

    def _apply(
        answer: ApprovalResume, tool: ToolSpec, call: ToolCall, grants: dict[str, str], edits: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        decision = answer.decision
        if decision.verdict == "reject":
            note = f" The operator's note: {decision.note}" if decision.note else ""
            return Deny(reason=f"An operator declined this action.{note}").model_dump()
        if decision.verdict == "edit" and decision.arguments is not None:
            try:
                tool.args.model_validate(decision.arguments)
            except ValidationError:
                return Deny(reason="An operator changed this action, but the change was not valid.").model_dump()
            edits[call_id(call)] = dict(decision.arguments)
        grants[call_id(call)] = answer.approval_id
        return Allow().model_dump()

    async def execute_tools(state: TeamState) -> TeamUpdate:
        current = await kit(state)
        spec, principal, tools = current.spec, current.principal, current.tools
        calls = pending_calls(state)
        decisions, grants, edits = state.get("decisions", {}), state.get("grants", {}), state.get("edits", {})

        async def run(call: ToolCall) -> ToolResult:
            decision = decisions.get(call_id(call), {"verdict": "deny", "reason": "Not authorized."})
            if decision["verdict"] != "allow":
                return ToolResult.error(decision["reason"])
            if spec.can_flag and call["name"] == FLAG_TOOL:
                return await flag(call)
            ctx = context(state, principal, call_id(call), grants.get(call_id(call)))
            arguments = {**edits.get(call_id(call), call["args"]), CONTEXT_ARG: encode_context(ctx, deps.context_key)}
            return await deps.tools.call(principal.subject, tools[call["name"]].server, call["name"], arguments)

        flagged: list[str] = []

        async def flag(call: ToolCall) -> ToolResult:
            if deps.raise_flag is None:
                return ToolResult.error(NO_FLAGS)
            try:
                pattern = PatternFlag.model_validate(call["args"])
            except ValidationError as error:
                return ToolResult.error(f"Invalid arguments: {error.errors()[0]['msg']}")
            work_item_id = await deps.raise_flag(state["work_item_id"], pattern, date.fromisoformat(state["today"]))
            if work_item_id is None:
                return ToolResult(output="Noted for the operations team.")
            flagged.append(work_item_id)
            return ToolResult(output=f"Flagged for the operations team as work item {work_item_id}.")

        timings: dict[str, float] = {}
        served: set[str] = set()

        def cache_key(call: ToolCall) -> str | None:
            tool = tools.get(call["name"])
            decision = decisions.get(call_id(call), {})
            if tool is None or not tool.cacheable or decision.get("verdict") != "allow":
                return None
            try:
                args = tool.args.model_validate(edits.get(call_id(call), call["args"]))
            except ValidationError:
                return None
            scope = {"audience": principal.audience, "day": state["today"]}
            return ReadCache.key(tool.name, args.model_dump(mode="json"), scope)

        async def answer(call: ToolCall) -> ToolResult:
            began = deps.clock.now()
            key = cache_key(call) if deps.read_cache is not None else None
            try:
                if key is not None and deps.read_cache is not None:
                    hit = deps.read_cache.get(key)
                    if hit is not None:
                        served.add(call_id(call))
                        return hit
                result = await run(call)
                if key is not None and deps.read_cache is not None:
                    deps.read_cache.put(key, result)
                return result
            finally:
                timings[call_id(call)] = (deps.clock.now() - began).total_seconds()

        started = deps.clock.now()
        results = await _run_in_order(calls, answer, lambda call: _is_read(tools, call))
        seconds = (deps.clock.now() - started).total_seconds()
        update: TeamUpdate = {}
        update[channel] = [
            ToolMessage(
                content=results[call_id(call)].output,
                tool_call_id=call_id(call),
                name=call["name"],
                status="success" if results[call_id(call)].ok else "error",
            )
            for call in calls
        ]
        verified = state.get("verified_customer_id")
        retrieved: dict[str, dict[str, Any]] = {}
        writes = list(state.get("writes", []))
        drafts = list(state.get("drafts", []))
        transferred = state.get("transferred", False)
        for call in calls:
            result = results[call_id(call)]
            verdict, reason = _verdict(decisions.get(call_id(call)), grants.get(call_id(call)))
            await emit(
                state,
                EventKind.TOOL_CALLED,
                {
                    "agent": name,
                    "version": spec.version_id,
                    "tool": call["name"],
                    "call_id": call_id(call),
                    "arguments": edits.get(call_id(call), call["args"]),
                    "ok": result.ok,
                    "verdict": verdict,
                    "reason": reason,
                    "approval_id": grants.get(call_id(call)),
                    "cached": call_id(call) in served,
                    "seconds": round(timings.get(call_id(call), 0.0), 3),
                    "result": summarize_result(call["name"], result),
                    "error": None if result.ok else result.output[:300],
                },
            )
            if not result.ok:
                continue
            tool = call["name"]
            if tool in IDENTITY_TOOLS and verified is None:
                verified = result.output.strip()
            elif tool in KNOWLEDGE_TOOLS:
                retrieved.update({passage["id"]: passage for passage in json.loads(result.output)})
            elif tool == DRAFT_TOOL:
                drafts.append(json.loads(result.output)["draft_id"])
            elif tool == TRANSFER_TOOL:
                transferred = True
            elif tool in tools and tools[tool].effect is Effect.WRITE:
                arguments = edits.get(call_id(call), call["args"])
                writes.append({"tool": tool, "arguments": arguments, "approval_id": grants.get(call_id(call))})
        entry = totals(state, name)
        used = Totals(
            **{
                **entry,
                "tool_calls": entry["tool_calls"] + len(calls),
                "seconds": round(entry["seconds"] + seconds, 3),
            }
        )
        update.update(
            verified_customer_id=verified,
            retrieved=retrieved,
            writes=writes,
            drafts=drafts,
            flags=[*state.get("flags", []), *flagged],
            transferred=transferred,
            ledger=ledger(used),
        )
        return update

    async def emit_output(state: TeamState) -> TeamUpdate | Command[str]:
        spec = (await kit(state)).spec
        message = last_ai(state.get(channel, []))
        text, closing = _closing_reply(message)
        if closing:
            state = cast("TeamState", {**state, channel: [*state.get(channel, []), *closing]})
        answer = _parse(spec.reply, text)
        if answer is None:
            model = deps.models.model_key(spec.role, spec.model)
            started = deps.clock.now()
            try:
                answer, report = await ask_typed(
                    deps.models,
                    spec.role,
                    spec.reply,
                    [SystemMessage(REPAIR), HumanMessage(text or "(empty)")],
                    model=model,
                )
            except ValueError:
                return await escalate(state, "unreadable")
            seconds = (deps.clock.now() - started).total_seconds()
            repaired: dict[str, JsonValue] = {
                "pass": totals(state, name)["model_calls"] + 1,
                "repair": True,
                "tools": [],
            }
            cost = await record_report(state, spec, model, report, seconds, repaired)
            await deps.limits.after_call(name, model, cost_usd=cost, ok=True)
            state = {**state, "ledger": ledger(charged(totals(state, name), report, cost, seconds))}
        problems: list[dict[str, Any]] = []
        if spec.checks_citations:
            windows = {
                passage_id: (date.fromisoformat(p["effective_date"]), date.fromisoformat(p["valid_until"]))
                for passage_id, p in state.get("retrieved", {}).items()
            }
            found = check_citations(getattr(answer, "citations", []), windows, date.fromisoformat(state["today"]))
            if found and state.get("repairs", 0) == 0:
                ids = ", ".join(problem.passage_id for problem in found)
                update: TeamUpdate = {"repairs": 1}
                update[channel] = [*closing, HumanMessage(CITATION_CHECK.format(ids=ids), id=f"check:{message.id}")]
                return update
            problems = [problem.model_dump() for problem in found]
        if isinstance(answer, SupportTurn) and deps.replies is not None:
            wrote = "\n".join(m.text for m in customer_messages(state.get(channel, [])))
            findings = await deps.replies.check(
                answer.reply, customer_id=state.get("verified_customer_id"), customer_wrote=wrote
            )
            if findings:
                payload: dict[str, JsonValue] = {"stage": "output", "findings": [f.model_dump() for f in findings]}
                await emit(state, EventKind.GUARDRAIL_BLOCKED, payload)
                return await escalate(state, "reply_blocked")
        conclusion = await conclude(name, state, answer, deps, lambda kind, payload: emit(state, kind, payload))
        return await hand_back(state, conclusion, {"citation_problems": problems})

    async def give_up(state: TeamState) -> Command[str]:
        return await escalate(state, state.get("stop_reason") or "max_model_calls")

    async def escalate(state: TeamState, reason: str) -> Command[str]:
        spec = (await kit(state)).spec
        note = f"The {name} agent stopped because {STOPPED_BECAUSE.get(reason, reason)}, and needs a person."
        stopped = Totals(**{**totals(state, name), "stop_reason": reason})
        update: TeamUpdate = {"transferred": True, "stop_reason": reason, "ledger": ledger(stopped)}
        if spec.reply is SupportTurn:
            turn = SupportTurn(reply=HANDOFF_REPLY, citations=[], status="transferred", summary=note)
            update["outputs"] = {**state.get("outputs", {}), name: turn.model_dump()}
        return await hand_back(state, Conclusion("human", update, brief=note))

    async def hand_back(state: TeamState, conclusion: Conclusion, extra: TeamUpdate | None = None) -> Command[str]:
        update: TeamUpdate = {**state, **conclusion.update, **(extra or {})}
        if conclusion.goto != "finalize":
            handoff: dict[str, Any] = {"from": name, "to": conclusion.goto, "brief": conclusion.brief}
            update["handoffs"] = [*state.get("handoffs", []), handoff]
            if conclusion.goto in CHANNELS:
                note = HumanMessage(conclusion.brief, id=f"{state['work_item_id']}:handoff:{name}")
                update[CHANNELS[conclusion.goto]] = [note]
                update["owner"] = conclusion.goto
            await emit(state, EventKind.AGENT_HANDOFF, handoff)
        return Command(graph=Command.PARENT, goto=conclusion.goto, update=update)

    graph = StateGraph(TeamState)
    graph.add_node("begin", begin)
    graph.add_node("call_model", call_model)
    graph.add_node("authorize", authorize)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("emit_output", emit_output)
    graph.add_node("give_up", give_up)
    graph.add_edge(START, "begin")
    graph.add_edge("begin", "call_model")
    graph.add_conditional_edges("call_model", after_model)
    graph.add_conditional_edges("authorize", after_authorize)
    graph.add_conditional_edges("approval_gate", after_authorize)
    graph.add_edge("execute_tools", "call_model")
    graph.add_edge("emit_output", "call_model")
    return graph


def last_ai(messages: Sequence[AnyMessage]) -> AIMessage:
    message = messages[-1]
    assert isinstance(message, AIMessage)
    return message


def call_id(call: ToolCall) -> str:
    assert call["id"] is not None
    return call["id"]


def _verdict(decision: dict[str, Any] | None, approval_id: str | None) -> tuple[str, str | None]:
    if decision is None or decision.get("verdict") != "allow":
        return "refused", (decision or {}).get("reason", "Not authorized.")
    return ("approved" if approval_id is not None else "allowed"), None


def _is_read(tools: dict[str, ToolSpec], call: ToolCall) -> bool:
    tool = tools.get(call["name"])
    return tool is not None and tool.effect is Effect.READ


async def _run_in_order(
    calls: Sequence[ToolCall],
    run: Callable[[ToolCall], Awaitable[ToolResult]],
    is_read: Callable[[ToolCall], bool],
) -> dict[str, ToolResult]:
    results: dict[str, ToolResult] = {}
    batch: list[ToolCall] = []

    async def flush() -> None:
        outputs = await asyncio.gather(*(run(call) for call in batch))
        results.update({call_id(call): output for call, output in zip(batch, outputs, strict=True)})
        batch.clear()

    for call in calls:
        if is_read(call):
            batch.append(call)
            continue
        await flush()
        results[call_id(call)] = await run(call)
    await flush()
    return results


def _replied(calls: Sequence[ToolCall]) -> bool:
    return any(call["name"] == REPLY_TOOL for call in calls)


def _closing_reply(message: AIMessage) -> tuple[str, list[ToolMessage]]:
    reply = next((call for call in message.tool_calls if call["name"] == REPLY_TOOL), None)
    if reply is None:
        return message.text, []
    closing = [
        ToolMessage(
            "Sent." if call is reply else "Not run: the turn ended with your reply.",
            tool_call_id=call_id(call),
            id=f"{message.id}:{call_id(call)}:result",
        )
        for call in message.tool_calls
    ]
    return json.dumps(reply["args"]), closing


def _parse[T: BaseModel](schema: type[T], text: str) -> T | None:
    try:
        return schema.model_validate_json(text)
    except ValidationError:
        return None

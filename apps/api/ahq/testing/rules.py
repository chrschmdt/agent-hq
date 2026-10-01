from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolCall, ToolMessage

from ahq.config import ModelRole
from ahq.sim.customer import RATING
from ahq.testing.chat import FakeChatModels, ScriptedChatModel

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ORDER = re.compile(r"#W\d{7}")
TICKET = re.compile(r"Ticket: (\S+)")
SEGMENT = re.compile(r"carrier (\w+), region (\w+)")
FOR_A_PERSON = (
    "fire",
    "smok",
    "shock",
    "burn",
    "spark",
    "lawyer",
    "attorney",
    "sue ",
    "lawsuit",
    "reporter",
    "journalist",
    "delete all my",
    "never placed",
    "hacked",
    "safety",
)
ANALYST_TOPICS = {"policy": "insights", "product": "insights", "account": "insights"}
QUERY_NAME = "where-is-my-order tickets by carrier and region"
ASK_EMAIL = "Happy to help. Could you share the email address on your account so I can look into this?"
ACCOUNT_TOOLS = ("get_order_details", "get_user_details", "return_delivered_order_items", "cancel_pending_order")
CRITERION = re.compile(r"^- (\w+): ", re.MULTILINE)
REVIEWED_AGENT = re.compile(r"^Agent: (\w+)", re.MULTILINE)
EXPECTED_OUTCOMES = "expectedOutcomes:"
THREATS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "data_theft",
        ("another customer", "other customer", "someone else's", "all customers", "every customer", "send it to"),
    ),
    (
        "fraud",
        ("manager approved", "already approved", "pre-approved", "i work here", "an employee", "security team"),
    ),
    ("abuse", ("i will hurt", "i know where you live", "you will regret")),
)


PACE: dict[ModelRole, float] = {"guard": 0.4, "dispatcher": 0.5, "customer": 0.6, "qa": 1.2}


class RuleChatModels(FakeChatModels):
    def __init__(self, pace: float = 0.0) -> None:
        rules: dict[ModelRole, Callable[[Sequence[BaseMessage]], AIMessage | str]] = {
            "dispatcher": dispatcher,
            "support": support,
            "customer": customer,
            "ops": ops,
            "insights": insights,
            "qa": qa,
            "guard": guard,
            "smoke": lambda _: "Hello from the smoke role.",
        }
        super().__init__(
            {
                role: ScriptedChatModel(replies=[rule], latency_seconds=pace * PACE.get(role, 1.0))
                for role, rule in rules.items()
            }
        )


def dispatcher(messages: Sequence[BaseMessage]) -> str:
    work = _text(messages[-1])
    kind = work.split("\n", 1)[0].removeprefix("Kind of work: ").strip()
    lowered = work.lower()
    if any(word in lowered for word in FOR_A_PERSON):
        route, priority = "human", "urgent"
    elif kind == "alert":
        route, priority = "ops", "high"
    elif kind == "flag":
        topic = re.search(r"Topic: (\w+)", work)
        route, priority = ANALYST_TOPICS.get(topic[1] if topic else "", "ops"), "normal"
    else:
        route, priority = "support", "normal"
    return json.dumps({"route": route, "priority": priority, "reason": f"Rules send {kind} work here.", "split": []})


def support(messages: Sequence[BaseMessage]) -> AIMessage:
    said = " ".join(_text(m) for m in messages if isinstance(m, HumanMessage))
    results = _results(messages)
    if "knowledge_search" not in results:
        query = {"query": _first_customer_message(messages)[:200]}
        return _call(messages, "knowledge_search", query, "Rule: search the knowledge base before answering.")
    user = results.get("find_user_id_by_email")
    if user is None:
        email = EMAIL.search(said)
        if email is None:
            return _reply(ASK_EMAIL, results, why="Rule: no email yet, so ask for one to find the account.")
        why = "Rule: the customer gave an email, so look up their account first."
        return _call(messages, "find_user_id_by_email", {"email": email[0]}, why)
    if user.startswith("Error"):
        text = "I could not find an account with that email. Could you check it for me?"
        return _reply(text, results, why="Rule: no account matches that email, so ask again.")
    order_id = ORDER.search(said)
    if order_id is None:
        text = "Thank you, I found your account. Which order is this about?"
        return _reply(text, results, why="Rule: the account is found but no order is named, so ask which one.")
    details = results.get("get_order_details")
    if details is None:
        why = f"Rule: the customer named order {order_id[0]}, so read it."
        return _call(messages, "get_order_details", {"order_id": order_id[0]}, why)
    order: dict[str, Any] = json.loads(details) if not details.startswith("Error") else {}
    wants_return = "return" in said.lower()
    if wants_return and order.get("status") == "delivered" and "return_delivered_order_items" not in results:
        payment = order["payment_history"][0]["payment_method_id"]
        items = [item["item_id"] for item in order["items"]]
        arguments = {"order_id": order_id[0], "item_ids": items, "payment_method_id": payment}
        why = "Rule: the customer asked for a return and the order is delivered, so return every item."
        return _call(messages, "return_delivered_order_items", arguments, why)
    if "return_delivered_order_items" in results:
        outcome = results["return_delivered_order_items"]
        if outcome.startswith("Error"):
            text = f"I could not return that order: {outcome.removeprefix('Error: ')}"
            return _reply(text, results, why="Rule: the return failed, so say why.")
        text = "Your return is requested; the refund goes back to the original payment method."
        return _reply(text, results, True, why="Rule: the return went through, so confirm it.")
    status = order.get("status", "not found")
    why = "Rule: tell the customer the order's status."
    return _reply(f"Order {order_id[0]} is {status}. Is there anything else I can do?", results, True, why=why)


def customer(messages: Sequence[BaseMessage]) -> str:
    last = _text(messages[-1])
    if last == RATING:
        return json.dumps({"score": 4, "reason": "The agent was quick and clear."})
    scenario = _text(messages[0])
    if "email" in last.lower():
        email = EMAIL.search(scenario)
        if email is not None:
            return f"Sure, it's {email[0]}."
        return "I don't remember my email, sorry. ###STOP###"
    if "which order" in last.lower():
        order_id = ORDER.search(scenario)
        return f"It's order {order_id[0]}." if order_id else "I'll check and come back. ###STOP###"
    return "Thanks, that's all I needed. ###STOP###"


def ops(messages: Sequence[BaseMessage]) -> AIMessage:
    results = _results(messages)
    if "analytics_run_sql" not in results:
        sql = (
            "SELECT s.carrier, s.region, count(*) AS asking FROM support.tickets t "
            "JOIN retail.shipments s ON s.order_id = t.order_id WHERE t.intent = 'where_is_my_order' "
            "GROUP BY 1, 2 ORDER BY 3 DESC"
        )
        why = "Rule: count where-is-my-order tickets by carrier and region first."
        return _call(messages, "analytics_run_sql", {"sql": sql}, why)
    brief = next((_text(m) for m in messages if isinstance(m, HumanMessage)), "")
    segment = SEGMENT.search(brief)
    carrier, region = (segment[1], segment[2]) if segment else (None, None)
    where = f"{carrier.title()} in the {region.title()}" if carrier and region else "one part of the store"
    report = {
        "title": f"Where-is-my-order tickets spiked for {where}",
        "summary": f"Customers of {where} are asking where their parcels are, far above the usual share.",
        "evidence": [{"query": QUERY_NAME, "excerpt": results["analytics_run_sql"][:300]}],
        "suspected_cause": "A stalled carrier hub; the parcels are in transit but not moving.",
        "affected": {"carrier": carrier, "region": region, "category": None, "item_id": None, "order_ids": []},
        "severity": "high" if segment else "medium",
        "recommended_action": "Tell affected customers about the delay and ask the carrier for an estimate.",
        "next": "insights",
        "brief": f"Please draft a customer notice about delays for {where}.",
    }
    return _answer(json.dumps(report), f"Rule: the alert's segment is {where}, so report it and hand it to Insights.")


def insights(messages: Sequence[BaseMessage]) -> AIMessage:
    results = _results(messages)
    if "knowledge_draft_article" not in results:
        body = (
            "# Delivery delays in your area\n\nSome parcels are taking longer than usual to arrive.\n\n"
            "## What to expect\n\nMost delayed parcels arrive within one to three extra days. Tracking may not update "
            "while a parcel waits at a hub.\n\n## When to contact us\n\nIf your parcel is more than three days past "
            "its promised date, contact support and we will check it for you."
        )
        arguments = {
            "doc_id": "help-delivery-delays-notice",
            "title": "Delivery delays in your area",
            "namespace": "shipping",
            "audience": "customer",
            "body": body,
        }
        return _call(messages, "knowledge_draft_article", arguments, "Rule: draft a delay notice for customers first.")
    drafted = results["knowledge_draft_article"]
    draft_id = None if drafted.startswith("Error") else json.loads(drafted)["draft_id"]
    proposals = [
        {
            "kind": "kb_article",
            "title": "Publish a delivery delay notice",
            "problem": "Customers do not know why their parcels are late.",
            "evidence": ["where-is-my-order tickets by carrier and region"],
            "proposal": "Publish the drafted notice for affected customers.",
            "expected_impact": "Fewer where-is-my-order tickets while the delay lasts.",
            "risk": "Low; the notice promises nothing beyond current policy.",
            "draft_id": draft_id,
        },
        {
            "kind": "agent_change",
            "title": "Brief Support on the delay",
            "problem": "Support answers each delayed customer from scratch.",
            "evidence": ["the incident's affected carrier and region"],
            "proposal": "Add the affected carrier and region to Support's context until the delay clears.",
            "expected_impact": "Faster, consistent answers.",
            "risk": "Stale context if the delay ends; remove it when the incident closes.",
            "draft_id": None,
        },
    ]
    answer = json.dumps({"summary": "A notice and a Support briefing.", "proposals": proposals})
    return _answer(answer, "Rule: propose publishing the draft and briefing Support.")


def guard(messages: Sequence[BaseMessage]) -> str:
    text = _text(messages[-1]).lower()
    for threat, phrases in THREATS:
        phrase = next((p for p in phrases if p in text), None)
        if phrase is not None:
            return json.dumps({"reasoning": f"The message says '{phrase}'.", "threat": threat})
    return json.dumps({"reasoning": "An ordinary request.", "threat": "none"})


def _text(message: BaseMessage) -> str:
    return message.text if isinstance(message.content, list) else str(message.content)


def _first_customer_message(messages: Sequence[BaseMessage]) -> str:
    return next((_text(m) for m in messages if isinstance(m, HumanMessage)), "help")


def _results(messages: Sequence[BaseMessage]) -> dict[str, str]:
    return {str(m.name): _text(m) for m in messages if isinstance(m, ToolMessage)}


def _call(messages: Sequence[BaseMessage], name: str, arguments: dict[str, Any], why: str) -> AIMessage:
    call_id = f"rule_{sum(isinstance(m, ToolMessage) for m in messages)}_{name}"
    call: ToolCall = {"name": name, "args": arguments, "id": call_id, "type": "tool_call"}
    return AIMessage(content=[{"type": "thinking", "thinking": why}], tool_calls=[call])


def _answer(text: str, why: str) -> AIMessage:
    return AIMessage(content=[{"type": "thinking", "thinking": why}, {"type": "text", "text": text}])


def _reply(text: str, results: dict[str, str], resolved: bool = False, *, why: str) -> AIMessage:
    passages = json.loads(results.get("knowledge_search", "[]") or "[]") if "knowledge_search" in results else []
    citations = [passages[0]["id"]] if resolved and passages else []
    turn = {
        "reply": text,
        "citations": citations,
        "status": "resolved" if resolved else "awaiting_customer",
        "summary": text[:120],
    }
    return _answer(json.dumps(turn), why)


def qa(messages: Sequence[BaseMessage]) -> str:
    request = _text(messages[-1])
    if EXPECTED_OUTCOMES in request:
        outcomes: list[str] = ast.literal_eval(request.partition(EXPECTED_OUTCOMES)[2].strip())
        met = [{"expected_outcome": o, "reasoning": "Rules cannot judge this.", "met": True} for o in outcomes]
        return json.dumps({"results": met})
    agent = REVIEWED_AGENT.search(request)
    verdicts = [
        {"criterion_id": criterion, "critique": critique, "verdict": verdict}
        for criterion in CRITERION.findall(request)
        for verdict, critique in [_grade(agent[1] if agent else "", criterion, request)]
    ]
    failed = sum(v["verdict"] == "fail" for v in verdicts)
    return json.dumps({"criteria": verdicts, "summary": f"Rules found {failed} problems."})


def _grade(agent: str, criterion: str, request: str) -> tuple[str, str]:
    run = request.partition("The run:")[2]
    if agent != "support":
        return "pass", "Rules see nothing wrong."
    looked_up = "agent calls find_user_id_by" in run
    match criterion:
        case "identity_verified":
            if any(f"agent calls {tool}" in run for tool in ACCOUNT_TOOLS):
                return ("pass", "The customer was looked up first.") if looked_up else ("fail", "No lookup first.")
            return "unknown", "The run never reached account details."
        case "citations_grounded":
            return ("pass", "The reply cites a passage.") if "[cites " in run else ("unknown", "No policy stated.")
        case "request_handled":
            wants_person = any(word in request.lower() for word in FOR_A_PERSON)
            if "agent calls transfer_to_human_agents" in run and not wants_person:
                return "fail", "The customer went to a person without the agent trying to help."
            return "pass", "The agent worked on the request."
        case _:
            return "pass", "Rules see nothing wrong."

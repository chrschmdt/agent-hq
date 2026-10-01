from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from ahq.domain import Event, EventKind
from ahq.domain.world import TicketMessage
from ahq.graphs import HANDOFF_REPLY, alert_brief
from ahq.retrieval import ingest, load_documents
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse
from ahq.testing.qdrant import LocalVectorStore
from tests.unit.graphs.harness import (
    ALERT,
    DRAFT,
    NOW,
    Harness,
    calls,
    incident,
    proposal,
    proposals,
    reply,
    route,
)

LATE_BY_REGION = ("analytics_run_sql", {"sql": "SELECT carrier, region, count(*) FROM retail.shipments GROUP BY 1, 2"})
FLAG = {
    "topic": "delivery",
    "summary": "A Northstar parcel to Ohio is four days late; the customer says neighbours wait too.",
    "ticket_ids": ["tk_1"],
}


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    store = LocalVectorStore()
    await ingest(store, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    yield Harness(store)
    await store.close()


async def kinds(harness: Harness) -> list[EventKind]:
    return [event.kind for event in await events(harness)]


async def events(harness: Harness) -> list[Event]:
    return await harness.events.read_after(0, limit=1000)


async def follow_up(harness: Harness, text: str) -> dict[str, Any]:
    await harness.world.add_message("tk_1", 2, TicketMessage(author="customer", body=text, created_at=NOW))
    return {"support_messages": [HumanMessage(text, id="tk_1#2")], "reply_position": 3}


async def test_a_new_ticket_goes_through_the_dispatcher_to_support(harness: Harness) -> None:
    dispatcher = harness.models.script("dispatcher", route("support", split=["cancel #W1", "change address on #W2"]))
    harness.models.script("support", reply("Sure."))
    output = await harness.run(await harness.open("Cancel #W1 and change the address on #W2.", owner=None))
    assert output.value["route"]["route"] == "support"
    assert output.value["route"]["split"] == ["cancel #W1", "change address on #W2"]
    assert output.value["owner"] == "support"
    assert output.value["disposition"] == "waiting_customer"
    assert "Kind of work: ticket" in str(dispatcher.calls[0][-1].content)
    routed = next(e for e in await events(harness) if e.kind is EventKind.WORK_ROUTED)
    assert routed.actor == "dispatcher"


async def test_a_follow_up_goes_to_the_owner_without_the_dispatcher(harness: Harness) -> None:
    dispatcher = harness.models.script("dispatcher", route("support"))
    harness.models.script("support", reply("How can I help?"), reply("Bye.", status="resolved"))
    await harness.run(await harness.open("Hi", owner=None))
    await harness.run(await follow_up(harness, "Thanks"))
    assert len(dispatcher.calls) == 1


async def test_an_unreadable_route_falls_back_to_the_default_owner(harness: Harness) -> None:
    harness.models.script("support", reply("Sure."))
    output = await harness.run(await harness.open("Hi", owner=None))
    assert output.value["route"]["route"] == "support"
    assert "could not be read" in output.value["route"]["reason"]


async def test_a_route_the_kind_of_work_does_not_allow_goes_to_the_default(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    harness.models.script("support", reply("Sure."))
    output = await harness.run(await harness.open("Where is my parcel?", owner=None))
    assert output.value["route"]["route"] == "support"
    assert output.value["route"]["reason"].startswith("ticket work cannot go to ops")


async def test_a_ticket_for_a_person_is_parked_with_a_holding_reply(harness: Harness) -> None:
    harness.models.script("dispatcher", route("human"))
    output = await harness.run(await harness.open("The heater caught fire.", owner=None))
    assert output.value["disposition"] == "escalated"
    ticket = await harness.world.ticket("tk_1")
    assert ticket is not None
    assert ticket.status == "escalated"
    assert ticket.messages[-1].body == HANDOFF_REPLY


async def test_an_alert_is_investigated_filed_and_handed_to_insights(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    ops = harness.models.script("ops", calls(LATE_BY_REGION), incident("insights"))
    insights = harness.models.script(
        "insights", calls(DRAFT), lambda messages: proposals(proposal(_draft_id(messages)))
    )
    output = await harness.run(harness.alert())

    assert output.value["disposition"] == "done"
    (query,) = harness.sql.queries
    assert "FROM retail.shipments" in query
    assert "Kind of work: alert" not in str(ops.calls[0][1].content)
    assert "northstar" in str(ops.calls[0][1].content)

    (filed,) = await harness.records.incidents()
    assert filed.incident_id == "inc_1"
    assert filed.report.affected.carrier == "northstar"
    note = insights.calls[0][1]
    assert isinstance(note, HumanMessage)
    assert str(note.content).startswith("Incident inc_1: Northstar parcels late in the Midwest")

    (saved,) = await harness.records.proposals()
    assert saved.incident_id == "inc_1"
    assert saved.proposal.draft_id is not None
    draft = await harness.records.draft(saved.proposal.draft_id)
    assert draft is not None
    assert draft.status == "pending"
    assert output.value["proposal_ids"] == [saved.proposal_id]
    assert [h["to"] for h in output.value["handoffs"]] == ["insights"]
    assert {EventKind.INCIDENT_FILED, EventKind.AGENT_HANDOFF, EventKind.PROPOSAL_CREATED} <= set(await kinds(harness))


async def test_agents_never_see_each_others_messages(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    harness.models.script("ops", calls(LATE_BY_REGION), incident("insights"))
    harness.models.script("insights", proposals())
    output = await harness.run(harness.alert())
    ops_ids = {m.id for m in output.value["ops_messages"]}
    insights_ids = {m.id for m in output.value["insights_messages"]}
    assert not ops_ids & insights_ids
    assert not any(isinstance(m, ToolMessage) for m in output.value["insights_messages"])
    assert not output.value.get("support_messages")


async def test_an_incident_that_needs_a_decision_goes_to_a_person(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    harness.models.script("ops", incident("human"))
    output = await harness.run(harness.alert())
    assert output.value["disposition"] == "escalated"
    assert [h["to"] for h in output.value["handoffs"]] == ["human"]
    assert len(await harness.records.incidents()) == 1


async def test_an_incident_that_needs_nothing_more_ends_the_work(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    harness.models.script("ops", incident("none"))
    output = await harness.run(harness.alert())
    assert output.value["disposition"] == "done"
    assert "handoffs" not in output.value


async def test_an_analyst_that_never_stops_is_handed_to_a_person(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    harness.models.script("ops", calls(LATE_BY_REGION))
    output = await harness.run(harness.alert())
    assert output.value["stop_reason"] == "max_model_calls"
    assert output.value["disposition"] == "escalated"
    assert await harness.records.incidents() == []


async def test_a_proposal_cannot_point_at_a_draft_it_did_not_make(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    harness.models.script("ops", incident("insights"))
    harness.models.script("insights", proposals(proposal("drf_invented")))
    await harness.run(harness.alert())
    (saved,) = await harness.records.proposals()
    assert saved.proposal.draft_id is None


async def test_support_flags_a_pattern_and_carries_on(harness: Harness) -> None:
    harness.models.script("support", calls(("flag_pattern", FLAG)), reply("Sorry about the delay."))
    output = await harness.run(await harness.open("My parcel is four days late."))
    (source, flag, today) = harness.flags[0]
    assert (source, flag.topic, str(today)) == ("wi_1", "delivery", "2026-06-15")
    assert output.value["flags"] == ["wi_flag"]
    result = next(m for m in output.value["support_messages"] if isinstance(m, ToolMessage))
    assert result.content == "Flagged for the operations team as work item wi_flag."


async def test_only_agents_that_may_flag_see_the_flag_tool(harness: Harness) -> None:
    support = harness.models.script("support", reply("Hi."))
    ops = harness.models.script("ops", incident("none"))
    harness.models.script("dispatcher", route("ops"))
    await harness.run(await harness.open("Hi"))
    await harness.run(harness.alert() | {"work_item_id": "wi_2"}, thread="th_wi_2")
    assert "flag_pattern" in _tool_names(support.bound_tools)
    assert "flag_pattern" not in _tool_names(ops.bound_tools)
    assert "analytics_run_sql" in _tool_names(ops.bound_tools)


async def test_writes_are_recorded_once_across_turns(harness: Harness) -> None:
    harness.models.script(
        "support",
        calls(("find_user_id_by_email", {"email": "ada@example.com"})),
        calls(("cancel_pending_order", {"order_id": "#pending", "reason": "no longer needed"}), start=2),
        reply("Cancelled."),
        reply("Anything else?"),
    )
    await harness.run(await harness.open("Cancel #pending."))
    output = await harness.run(await follow_up(harness, "Thanks"))
    assert [write["tool"] for write in output.value["writes"]] == ["cancel_pending_order"]


def _draft_id(messages: object) -> str:
    assert isinstance(messages, list)
    result = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == DRAFT[0])
    return json.loads(str(result.content))["draft_id"]


def _tool_names(tools: list[object]) -> set[str]:
    return {tool["function"]["name"] for tool in tools if isinstance(tool, dict)}  # type: ignore[index]


async def test_an_answer_that_cannot_be_read_goes_to_a_person(harness: Harness) -> None:
    harness.models.script("dispatcher", route("ops"))
    harness.models.script("ops", "The parcels are late, I think.", "Still not JSON.")
    output = await harness.run(harness.alert())
    assert output.value["disposition"] == "escalated"
    assert output.value["stop_reason"] == "unreadable"
    assert await harness.records.incidents() == []


def test_an_alerts_brief_reads_the_same_whatever_order_its_segment_was_stored_in() -> None:
    stored = ALERT.model_copy(update={"segment": {"region": "midwest", "carrier": "northstar"}})
    assert alert_brief(stored) == alert_brief(ALERT)
    assert "for carrier northstar, region midwest was" in alert_brief(stored)

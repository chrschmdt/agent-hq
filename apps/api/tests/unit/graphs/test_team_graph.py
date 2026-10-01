from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ahq.domain import ApprovalDecision, Event, EventKind
from ahq.domain.world import TicketMessage
from ahq.graphs import HANDOFF_REPLY
from ahq.ports import REPLY_TOOL
from ahq.retrieval import ingest, load_documents
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse
from ahq.testing.qdrant import LocalVectorStore
from ahq.tools import AUTHENTICATE_FIRST
from tests.unit.graphs.harness import NOW, Harness, calls, citing_first_passage, reply
from tests.unit.retail.sample import CARD

FIND_ADA = ("find_user_id_by_email", {"email": "ada@example.com"})
RETURN_BOTH = (
    "return_delivered_order_items",
    {"order_id": "#delivered", "item_ids": ["mug_small", "lamp_white"], "payment_method_id": CARD},
)
APPROVE = ApprovalDecision(verdict="approve")


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    store = LocalVectorStore()
    await ingest(store, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    yield Harness(store)
    await store.close()


async def events(harness: Harness) -> list[Event]:
    return await harness.events.read_after(0, limit=1000)


async def test_a_ticket_is_answered_with_a_cited_policy(harness: Harness) -> None:
    harness.models.script(
        "support",
        calls(("knowledge_search", {"query": "where does a refund go"})),
        citing_first_passage,
    )
    output = await harness.run(await harness.open("Where would my refund go?"))
    assert output.value["disposition"] == "waiting_customer"
    turn = output.value["outputs"]["support"]
    assert turn["citations"]
    assert turn["citations"][0] in output.value["retrieved"]
    ticket = await harness.world.ticket("tk_1")
    assert ticket is not None
    assert [m.author for m in ticket.messages] == ["customer", "agent"]
    assert ticket.status == "waiting_customer"
    replied = next(e for e in await events(harness) if e.kind is EventKind.TICKET_REPLIED)
    assert replied.payload["citations"] == turn["citations"]


async def test_the_customer_must_be_authenticated_before_their_orders(harness: Harness) -> None:
    harness.models.script(
        "support",
        calls(("get_order_details", {"order_id": "#delivered"})),
        calls(FIND_ADA, start=2),
        calls(("get_order_details", {"order_id": "#delivered"}), start=3),
        reply("Your order was delivered.", status="resolved"),
    )
    output = await harness.run(await harness.open("Where is order #delivered?"))
    tool_messages = [m for m in output.value["support_messages"] if isinstance(m, ToolMessage)]
    assert tool_messages[0].content == f"Error: {AUTHENTICATE_FIRST}"
    assert tool_messages[1].content == "ada_1"
    assert json.loads(str(tool_messages[2].content))["status"] == "delivered"
    assert output.value["verified_customer_id"] == "ada_1"
    assert output.value["disposition"] == "done"


async def test_every_tool_call_gets_an_answer_in_the_same_channel(harness: Harness) -> None:
    harness.models.script("support", calls(FIND_ADA, ("list_all_product_types", {})), reply("Done.", status="resolved"))
    output = await harness.run(await harness.open("Hi"))
    messages = output.value["support_messages"]
    asked = [c["id"] for m in messages if isinstance(m, AIMessage) for c in m.tool_calls]
    answered = [m.tool_call_id for m in messages if isinstance(m, ToolMessage)]
    assert asked == answered == ["call_1", "call_2"]


async def test_a_large_refund_waits_for_approval_and_runs_once_after_it(harness: Harness) -> None:
    harness.models.script("support", calls(FIND_ADA), calls(RETURN_BOTH, start=2), reply("Your return is requested."))
    paused = await harness.run(await harness.open("Return everything from #delivered, please."))
    (pending,) = paused.interrupts
    assert pending.value["action"] == "return_delivered_order_items"
    assert pending.value["cost_usd"] == 50.0
    assert (await harness.retail.snapshot()).orders["#delivered"].status == "delivered"

    done = await harness.run(await harness.answer(paused, APPROVE))
    assert not done.interrupts
    assert (await harness.retail.snapshot()).orders["#delivered"].status == "return requested"
    record = await harness.retail.recorded_call("th_wi_1:call_2")
    assert record is not None
    assert record.approval_id is not None
    assert done.value["writes"] == [
        {"tool": "return_delivered_order_items", "arguments": RETURN_BOTH[1], "approval_id": record.approval_id}
    ]


async def test_a_rejected_action_is_reported_to_the_agent_and_never_runs(harness: Harness) -> None:
    harness.models.script("support", calls(FIND_ADA), calls(RETURN_BOTH, start=2), reply("I could not do that."))
    paused = await harness.run(await harness.open("Return everything."))
    done = await harness.run(await harness.answer(paused, ApprovalDecision(verdict="reject", note="Needs a photo")))
    rejected = next(
        m for m in done.value["support_messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "call_2"
    )
    assert rejected.content == "Error: An operator declined this action. The operator's note: Needs a photo"
    assert (await harness.retail.snapshot()).orders["#delivered"].status == "delivered"
    assert await harness.retail.recorded_call("th_wi_1:call_2") is None


async def test_an_edited_action_runs_with_the_operators_arguments(harness: Harness) -> None:
    harness.models.script("support", calls(FIND_ADA), calls(RETURN_BOTH, start=2), reply("Returned the lamp."))
    paused = await harness.run(await harness.open("Return everything."))
    lamp_only = {**RETURN_BOTH[1], "item_ids": ["lamp_white"]}
    await harness.run(await harness.answer(paused, ApprovalDecision(verdict="edit", arguments=lamp_only)))
    assert (await harness.retail.snapshot()).orders["#delivered"].return_items == ["lamp_white"]


async def test_two_gated_calls_pause_one_after_the_other(harness: Harness) -> None:
    harness.models.script(
        "support", calls(FIND_ADA), calls(RETURN_BOTH, RETURN_BOTH, start=2), reply("Handled.", status="resolved")
    )
    first = await harness.run(await harness.open("Return everything, twice."))
    second = await harness.run(await harness.answer(first, APPROVE))
    assert [len(first.interrupts), len(second.interrupts)] == [1, 1]
    assert first.interrupts[0].id != second.interrupts[0].id
    assert (await harness.retail.snapshot()).orders["#delivered"].status == "delivered"
    done = await harness.run(await harness.answer(second, APPROVE))
    results = [m for m in done.value["support_messages"] if isinstance(m, ToolMessage) and m.name == RETURN_BOTH[0]]
    assert json.loads(str(results[0].content))["status"] == "return requested"
    assert results[1].content == "Error: Non-delivered order cannot be returned"


async def test_a_citation_that_was_never_retrieved_gets_one_retry(harness: Harness) -> None:
    support = harness.models.script(
        "support",
        reply("Refunds take a week.", citations=["policy-refunds@v9#9"]),
        reply("Refunds take a week.", citations=["policy-refunds@v9#9"]),
    )
    output = await harness.run(await harness.open("How long do refunds take?"))
    assert len(support.calls) == 2
    assert isinstance(support.calls[1][-1], HumanMessage)
    assert "Automatic check" in str(support.calls[1][-1].content)
    assert output.value["citation_problems"] == [{"passage_id": "policy-refunds@v9#9", "problem": "not_retrieved"}]


async def test_an_agent_that_never_stops_is_handed_to_a_person(harness: Harness) -> None:
    harness.models.script("support", calls(("list_all_product_types", {})))
    output = await harness.run(await harness.open("Hi"))
    assert output.value["stop_reason"] == "max_model_calls"
    assert output.value["disposition"] == "escalated"
    assert output.value["outputs"]["support"]["reply"] == HANDOFF_REPLY
    assert (await harness.world.ticket("tk_1")).status == "escalated"  # type: ignore[union-attr]
    assert EventKind.TICKET_CLOSED in {e.kind for e in await events(harness)}


async def test_a_reply_that_is_not_json_is_repaired(harness: Harness) -> None:
    harness.models.script(
        "support",
        AIMessage(content="Sure, happy to help!"),
        json.dumps({"reply": "Sure, happy to help!", "citations": [], "status": "awaiting_customer", "summary": "Hi"}),
    )
    output = await harness.run(await harness.open("Hi"))
    assert output.value["outputs"]["support"]["reply"] == "Sure, happy to help!"


async def test_the_next_customer_message_continues_the_same_thread(harness: Harness) -> None:
    harness.models.script("support", reply("How can I help?"), reply("Goodbye.", status="resolved"))
    await harness.run(await harness.open("Hi"))
    await harness.world.add_message("tk_1", 2, TicketMessage(author="customer", body="Nothing, thanks", created_at=NOW))
    output = await harness.run(
        {"support_messages": [HumanMessage("Nothing, thanks", id="tk_1#2")], "reply_position": 3}
    )
    assert output.value["disposition"] == "done"
    ticket = await harness.world.ticket("tk_1")
    assert ticket is not None
    assert [m.body for m in ticket.messages] == ["Hi", "How can I help?", "Nothing, thanks", "Goodbye."]
    assert ticket.status == "resolved"


async def test_a_turn_ended_with_a_reply_call_answers_the_customer_and_carries_on(harness: Harness) -> None:
    turn = {"reply": "How can I help?", "citations": [], "status": "awaiting_customer", "summary": "Greeted."}
    harness.models.script(
        "support",
        calls((REPLY_TOOL, turn), ("get_user_details", {"user_id": "ada_1"})),
        reply("Goodbye.", status="resolved"),
    )
    first = await harness.run(await harness.open("Hi"))
    assert first.value["outputs"]["support"]["reply"] == "How can I help?"
    results = [m for m in first.value["support_messages"] if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.content) for m in results] == [
        ("call_1", "Sent."),
        ("call_2", "Not run: the turn ended with your reply."),
    ]
    await harness.world.add_message("tk_1", 2, TicketMessage(author="customer", body="Nothing, thanks", created_at=NOW))
    output = await harness.run(
        {"support_messages": [HumanMessage("Nothing, thanks", id="tk_1#2")], "reply_position": 3}
    )
    assert output.value["disposition"] == "done"
    ticket = await harness.world.ticket("tk_1")
    assert ticket is not None
    assert [m.body for m in ticket.messages] == ["Hi", "How can I help?", "Nothing, thanks", "Goodbye."]


async def test_a_simulated_tickets_reply_carries_the_simulated_days_time() -> None:
    store = LocalVectorStore()
    await ingest(store, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    simulated = datetime(2026, 6, 15, 14, 35, tzinfo=UTC)

    async def store_time(work_item_id: str) -> datetime | None:
        return simulated if work_item_id == "wi_1" else None

    harness = Harness(store, store_time=store_time)
    harness.models.script("support", reply("Your order is on its way.", status="resolved"))
    await harness.run(await harness.open("Where is my order?"))
    ticket = await harness.world.ticket("tk_1")
    assert ticket is not None
    assert ticket.messages[-1].created_at == simulated
    assert ticket.resolved_at == simulated
    await store.close()

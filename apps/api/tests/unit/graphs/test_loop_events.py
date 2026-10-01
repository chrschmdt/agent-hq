from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from ahq.adapters.clock import ManualClock
from ahq.config import load_guard_config
from ahq.domain import ApprovalDecision, Event, EventKind
from ahq.graphs import reasoning_of, thread_view
from ahq.guardrails import InputCheck
from ahq.retrieval import ingest, load_documents
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse
from ahq.testing.qdrant import LocalVectorStore
from ahq.tools import AUTHENTICATE_FIRST, ReadCache
from tests.unit.graphs.harness import NOW, Harness, calls, reply
from tests.unit.retail.sample import CARD

FIND_ADA = ("find_user_id_by_email", {"email": "ada@example.com"})
RETURN_BOTH = (
    "return_delivered_order_items",
    {"order_id": "#delivered", "item_ids": ["mug_small", "lamp_white"], "payment_method_id": CARD},
)
PRODUCTS = ("list_all_product_types", {})


@pytest.fixture
async def store() -> AsyncIterator[LocalVectorStore]:
    store = LocalVectorStore()
    await ingest(store, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    yield store
    await store.close()


async def of_kind(harness: Harness, kind: EventKind) -> list[Event]:
    return [e for e in await harness.events.read_after(0, limit=1000) if e.kind is kind]


def thinking(text: str, message: AIMessage) -> AIMessage:
    content = [{"type": "thinking", "thinking": text}]
    if message.text:
        content.append({"type": "text", "text": str(message.text)})
    return message.model_copy(update={"content": content})


async def test_each_model_call_names_its_pass_its_message_and_the_tools_it_asked_for(store: LocalVectorStore) -> None:
    harness = Harness(store)
    harness.models.script("support", calls(FIND_ADA, PRODUCTS), reply("Done.", status="resolved"))
    output = await harness.run(await harness.open("Hi, I'm ada@example.com."))
    first, second = await of_kind(harness, EventKind.MODEL_CALLED)
    assert (first.payload["pass"], second.payload["pass"]) == (1, 2)
    assert first.payload["tools"] == [
        {"id": "call_1", "name": "find_user_id_by_email"},
        {"id": "call_2", "name": "list_all_product_types"},
    ]
    assert second.payload["tools"] == []
    ids = [m.id for m in output.value["support_messages"] if isinstance(m, AIMessage)]
    assert [first.payload["message_id"], second.payload["message_id"]] == ids
    assert all(ids)


async def test_a_tool_call_records_its_verdict_its_time_and_what_came_back(store: LocalVectorStore) -> None:
    harness = Harness(store)
    harness.models.script(
        "support",
        calls(("get_order_details", {"order_id": "#delivered"})),
        calls(FIND_ADA, start=2),
        calls(("knowledge_search", {"query": "where does a refund go"}), start=3),
        reply("Found it.", status="resolved"),
    )
    await harness.run(await harness.open("Where is order #delivered?"))
    refused, found, searched = await of_kind(harness, EventKind.TOOL_CALLED)
    assert (refused.payload["verdict"], refused.payload["reason"]) == ("refused", AUTHENTICATE_FIRST)
    assert refused.payload["result"] == {}
    assert found.payload["verdict"] == "allowed"
    assert found.payload["reason"] is None
    assert (found.payload["call_id"], found.payload["result"]) == ("call_2", {"text": "ada_1"})
    assert found.payload["seconds"] == 0.0
    assert found.payload["cached"] is False
    result = searched.payload["result"]
    assert isinstance(result, dict)
    passages = result["passages"]
    assert isinstance(passages, list)
    assert passages
    assert all(isinstance(p, str) and "@v" in p for p in passages)


async def test_an_approved_call_says_so(store: LocalVectorStore) -> None:
    harness = Harness(store)
    harness.models.script("support", calls(FIND_ADA), calls(RETURN_BOTH, start=2), reply("Your return is requested."))
    paused = await harness.run(await harness.open("Return everything from #delivered, please."))
    await harness.run(await harness.answer(paused, ApprovalDecision(verdict="approve")))
    returned = (await of_kind(harness, EventKind.TOOL_CALLED))[-1]
    assert returned.payload["verdict"] == "approved"
    assert returned.payload["approval_id"] is not None
    assert returned.payload["result"] == {
        "status": "return requested",
        "order_id": "#delivered",
        "user_id": "ada_1",
        "items": 2,
    }


async def test_a_repeated_read_is_answered_from_the_read_cache(store: LocalVectorStore) -> None:
    harness = Harness(store, read_cache=ReadCache(ManualClock(NOW)))
    harness.models.script("support", calls(PRODUCTS), calls(PRODUCTS, start=2), reply("Here they are."))
    await harness.run(await harness.open("What do you sell?"))
    first, second = await of_kind(harness, EventKind.TOOL_CALLED)
    assert (first.payload["cached"], second.payload["cached"]) == (False, True)
    assert first.payload["result"] == second.payload["result"]


async def test_the_screens_call_carries_its_verdict(store: LocalVectorStore) -> None:
    harness = Harness(store, screen=InputCheck.of(load_guard_config().input))
    harness.models.script("guard", json.dumps({"reasoning": "An ordinary request.", "threat": "none"}))
    harness.models.script("support", reply("Could you share your email?"))
    await harness.run(await harness.open("Where is my order?"))
    [screened] = [e for e in await of_kind(harness, EventKind.MODEL_CALLED) if e.actor == "guard"]
    assert screened.payload["screening"] == {
        "blocked": False,
        "threat": "none",
        "reason": "An ordinary request.",
        "by": "model",
    }


async def test_the_thread_reads_as_messages_with_their_reasoning(store: LocalVectorStore) -> None:
    harness = Harness(store)
    harness.models.script(
        "support",
        thinking("Authenticate first.", calls(FIND_ADA)),
        thinking("Answer and close.", reply("You're all set.", status="resolved")),
    )
    await harness.run(await harness.open("Hi, I'm ada@example.com."))
    view = thread_view(await harness.state())  # type: ignore[arg-type]
    messages = view.channels["support"]
    assert [m.kind for m in messages] == ["customer", "model", "tool", "model"]
    assert [m.reasoning for m in messages if m.kind == "model"] == ["Authenticate first.", "Answer and close."]
    assert messages[1].tool_calls[0].name == "find_user_id_by_email"
    assert (messages[2].tool_call_id, messages[2].ok, messages[2].text) == ("call_1", True, "ada_1")
    assert json.loads(messages[3].text)["reply"] == "You're all set."
    assert view.verified_customer_id == "ada_1"
    assert view.outputs["support"]["status"] == "resolved"


def test_reasoning_is_read_only_from_thinking_blocks() -> None:
    assert reasoning_of(AIMessage(content="plain")) is None
    assert reasoning_of(AIMessage(content=[{"type": "text", "text": "x"}])) is None
    blocks: list[str | dict[str, Any]] = [
        {"type": "thinking", "thinking": "One."},
        {"type": "thinking", "thinking": " Two. "},
    ]
    assert reasoning_of(AIMessage(content=blocks)) == "One.\n\nTwo."

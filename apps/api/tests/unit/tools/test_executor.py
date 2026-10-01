from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryApprovalStore, MemoryWorldRepo
from ahq.config import ApprovalPolicy, load_retrieval_config
from ahq.domain import ApprovalDecision, ApprovalRequest, WorkItemId
from ahq.domain.retail import Fulfillment, RetailSnapshot
from ahq.domain.world import Shipment
from ahq.ports import WorldRepo
from ahq.retail import InMemoryRetailRepo
from ahq.retrieval import HybridRetriever, ingest, load_documents
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse, OverlapReranker
from ahq.testing.qdrant import LocalVectorStore
from ahq.tools import (
    AUTHENTICATE_FIRST,
    CATALOG,
    CONTEXT_ARG,
    Autonomy,
    CallContext,
    Principal,
    ToolDeps,
    ToolExecutor,
    encode_context,
)
from tests.unit.retail.sample import CARD, sample_store

KEY = "context-key"
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
SUPPORT = Principal(
    subject="support", autonomy=Autonomy.ACT, tools=frozenset(CATALOG), customer_scoped=True, audience="customer"
)
RETURN_BOTH = {"order_id": "#delivered", "item_ids": ["mug_small", "lamp_white"], "payment_method_id": CARD}


class Harness:
    def __init__(
        self, store: LocalVectorStore, *, retail: RetailSnapshot | None = None, world: WorldRepo | None = None
    ) -> None:
        self.clock = ManualClock(NOW)
        self.retail = InMemoryRetailRepo(retail or sample_store())
        self.approvals = MemoryApprovalStore(self.clock)
        embedder = HashEmbedder()
        retriever = HybridRetriever(store, embedder, OverlapReranker(), HashingSparse(), load_retrieval_config())
        deps = ToolDeps(
            retail=self.retail, retriever=retriever, approvals=self.approvals, clock=self.clock, world=world
        )
        self.executor = ToolExecutor(deps, context_key=KEY, policy=ApprovalPolicy(refund_limit_usd=45.0))
        self.interrupts = 0

    def ctx(self, *, call: str = "call_1", verified: str | None = "ada_1", approval_id: str | None = None) -> str:
        context = CallContext(
            work_item_id="wi_1",
            thread_id="th_wi_1",
            tool_call_id=call,
            subject="support",
            verified_customer_id=verified,
            approval_id=approval_id,
            as_of=date(2026, 6, 15),
            expires_at=NOW + timedelta(minutes=5),
        )
        return encode_context(context, KEY)

    async def call(self, name: str, arguments: dict[str, Any], ctx: str | None = None) -> str:
        if ctx is not None:
            arguments = {**arguments, CONTEXT_ARG: ctx}
        return (await self.executor.call(SUPPORT, name, arguments)).output

    async def approve(self, arguments: dict[str, Any], *, edited: dict[str, Any] | None = None) -> str:
        request = ApprovalRequest(action="return_delivered_order_items", arguments=arguments, reason="refund")
        self.interrupts += 1
        approval = await self.approvals.open(WorkItemId("wi_1"), f"interrupt_{self.interrupts}", request)
        verdict = "edit" if edited is not None else "approve"
        await self.approvals.decide(approval.id, ApprovalDecision(verdict=verdict, arguments=edited), "operator")
        return approval.id


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    store = LocalVectorStore()
    await ingest(store, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    yield Harness(store)
    await store.close()


async def test_bad_calls_come_back_as_errors(harness: Harness) -> None:
    assert await harness.call("drop_tables", {}) == "Error: Tool 'drop_tables' not found."
    assert (await harness.call("get_order_details", {})).startswith("Error: Invalid arguments for get_order_details")
    assert await harness.call("get_order_details", {"order_id": "#delivered"}) == f"Error: {AUTHENTICATE_FIRST}"
    forged = harness.ctx()[:-2] + "xx"
    assert (await harness.call("get_order_details", {"order_id": "#delivered"}, forged)).startswith("Error: Refused")


async def test_reads_return_what_tau3_returns(harness: Harness) -> None:
    assert await harness.call("find_user_id_by_email", {"email": "ada@example.com"}) == "ada_1"
    order = json.loads(await harness.call("get_order_details", {"order_id": "#delivered"}, harness.ctx()))
    assert order["status"] == "delivered"
    other = await harness.call("get_order_details", {"order_id": "#delivered"}, harness.ctx(verified="bob_2"))
    assert other.startswith("Error: This belongs to a different customer")


async def test_an_order_is_tracked_parcel_by_parcel(harness: Harness) -> None:
    untracked = await harness.call("track_order", {"order_id": "#delivered"}, harness.ctx())
    assert untracked == "No tracking information for order #delivered."

    store = sample_store()
    parcel = Fulfillment(tracking_id=["TRK1"], item_ids=["mug_small", "lamp_white"])
    delivered = store.orders["#delivered"].model_copy(update={"fulfillments": [parcel]})
    store = store.model_copy(update={"orders": {**store.orders, "#delivered": delivered}})
    world = MemoryWorldRepo()
    await world.save_shipment(
        Shipment(
            tracking_id="TRK1",
            order_id="#delivered",
            carrier="Northstar Post",
            state="NY",
            region="northeast",
            status="delivered",
            shipped_at=NOW - timedelta(days=5),
            promised_at=NOW - timedelta(days=2),
            delivered_at=NOW - timedelta(days=1),
        )
    )
    tracked = Harness(LocalVectorStore(), retail=store, world=world)
    (seen,) = json.loads(await tracked.call("track_order", {"order_id": "#delivered"}, tracked.ctx()))
    assert (seen["carrier"], seen["status"]) == ("Northstar Post", "delivered")
    assert seen["delivered_at"] == (NOW - timedelta(days=1)).isoformat()
    other = await tracked.call("track_order", {"order_id": "#delivered"}, tracked.ctx(verified="bob_2"))
    assert other.startswith("Error: This belongs to a different customer")


async def test_a_refund_over_the_limit_needs_an_approval_for_exactly_that_call(harness: Harness) -> None:
    waiting = await harness.call("return_delivered_order_items", RETURN_BOTH, harness.ctx())
    assert waiting.startswith("Error: Approval required. Refund of $50.00 is over the $45.00 limit.")

    small = {**RETURN_BOTH, "item_ids": ["lamp_white"]}
    other_action = await harness.approve(small)
    refused = await harness.call("return_delivered_order_items", RETURN_BOTH, harness.ctx(approval_id=other_action))
    assert refused == "Error: Refused: the approval was for a different action."

    approval_id = await harness.approve(RETURN_BOTH)
    done = json.loads(
        await harness.call("return_delivered_order_items", RETURN_BOTH, harness.ctx(approval_id=approval_id))
    )
    assert done["status"] == "return requested"
    record = await harness.retail.recorded_call("th_wi_1:call_1")
    assert record is not None
    assert (record.approval_id, record.subject, record.tool) == (approval_id, "support", "return_delivered_order_items")


async def test_an_edited_approval_covers_the_edited_arguments(harness: Harness) -> None:
    small = {**RETURN_BOTH, "item_ids": ["lamp_white"]}
    approval_id = await harness.approve(RETURN_BOTH, edited=small)
    assert (
        await harness.call("return_delivered_order_items", RETURN_BOTH, harness.ctx(approval_id=approval_id))
    ).startswith("Error: Refused")
    done = json.loads(await harness.call("return_delivered_order_items", small, harness.ctx(approval_id=approval_id)))
    assert done["return_items"] == ["lamp_white"]


async def test_a_redelivered_write_returns_the_first_result_and_writes_once(harness: Harness) -> None:
    cancel = {"order_id": "#pending", "reason": "no longer needed"}
    first = await harness.call("cancel_pending_order", cancel, harness.ctx(call="call_9"))
    again = await harness.call("cancel_pending_order", cancel, harness.ctx(call="call_9"))
    assert again == first
    assert json.loads(first)["status"] == "cancelled"
    fresh = await harness.call("cancel_pending_order", cancel, harness.ctx(call="call_10"))
    assert fresh == "Error: Non-pending order cannot be cancelled"


async def test_search_returns_citable_passages_in_effect(harness: Harness) -> None:
    passages = json.loads(await harness.call("knowledge_search", {"query": "return window days"}, harness.ctx()))
    assert passages
    assert all(p["id"].count("@v") == 1 for p in passages)
    assert {p["version"] for p in passages if p["id"].startswith("policy-returns@")} <= {1}
    article = json.loads(await harness.call("knowledge_get_article", {"doc_id": "policy-returns"}, harness.ctx()))
    assert [p["id"] for p in article][:2] == ["policy-returns@v1#0", "policy-returns@v1#1"]
    missing = await harness.call("knowledge_get_article", {"doc_id": "nope"}, harness.ctx())
    assert missing == "Error: No article 'nope' is in effect."

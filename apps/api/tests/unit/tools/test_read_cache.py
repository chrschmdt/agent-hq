from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryApprovalStore
from ahq.config import ApprovalPolicy, load_retrieval_config
from ahq.domain import ToolResult
from ahq.retail import InMemoryRetailRepo
from ahq.retrieval import (
    Audience,
    HybridRetriever,
    Passage,
    SearchRequest,
    SearchResult,
    ingest,
    load_documents,
)
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse, OverlapReranker
from ahq.testing.qdrant import LocalVectorStore
from ahq.tools import (
    CATALOG,
    CONTEXT_ARG,
    Autonomy,
    CallContext,
    Principal,
    ReadCache,
    ToolDeps,
    ToolExecutor,
    encode_context,
)
from tests.unit.retail.sample import sample_store

KEY = "context-key"
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
SUPPORT = Principal(
    subject="support", autonomy=Autonomy.ACT, tools=frozenset(CATALOG), customer_scoped=True, audience="customer"
)
SEARCH = {"query": "how long do refunds take"}


class CountingRetriever:
    def __init__(self, inner: HybridRetriever) -> None:
        self.inner = inner
        self.searches = 0

    async def search(self, request: SearchRequest, *, trace: bool = False) -> SearchResult:
        self.searches += 1
        return await self.inner.search(request, trace=trace)

    async def article(self, doc_id: str, as_of: date, audience: Audience) -> list[Passage]:
        return await self.inner.article(doc_id, as_of, audience)


@pytest.fixture
async def world() -> AsyncIterator[tuple[ToolExecutor, CountingRetriever, ReadCache, ManualClock]]:
    store = LocalVectorStore()
    await ingest(store, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    clock = ManualClock(NOW)
    inner = HybridRetriever(store, HashEmbedder(), OverlapReranker(), HashingSparse(), load_retrieval_config())
    retriever = CountingRetriever(inner)
    deps = ToolDeps(
        retail=InMemoryRetailRepo(sample_store()),
        retriever=retriever,
        approvals=MemoryApprovalStore(clock),
        clock=clock,
    )
    cache = ReadCache(clock, ttl=timedelta(minutes=10))
    executor = ToolExecutor(deps, context_key=KEY, policy=ApprovalPolicy(refund_limit_usd=45.0), cache=cache)
    yield executor, retriever, cache, clock
    await store.close()


def ctx(clock: ManualClock, day: date = date(2026, 6, 15)) -> str:
    context = CallContext(
        work_item_id="wi_1",
        thread_id="th_wi_1",
        tool_call_id="call_1",
        subject="support",
        as_of=day,
        expires_at=clock.now() + timedelta(minutes=5),
    )
    return encode_context(context, KEY)


async def test_a_repeated_search_is_answered_from_the_cache(
    world: tuple[ToolExecutor, CountingRetriever, ReadCache, ManualClock],
) -> None:
    executor, retriever, cache, clock = world
    first = await executor.call(SUPPORT, "knowledge_search", {**SEARCH, CONTEXT_ARG: ctx(clock)})
    again = await executor.call(SUPPORT, "knowledge_search", {**SEARCH, CONTEXT_ARG: ctx(clock)})
    assert first == again
    assert retriever.searches == 1
    assert (cache.hits, cache.misses) == (1, 1)


async def test_another_day_another_audience_or_a_stale_entry_searches_again(
    world: tuple[ToolExecutor, CountingRetriever, ReadCache, ManualClock],
) -> None:
    executor, retriever, cache, clock = world
    await executor.call(SUPPORT, "knowledge_search", {**SEARCH, CONTEXT_ARG: ctx(clock)})
    await executor.call(SUPPORT, "knowledge_search", {**SEARCH, CONTEXT_ARG: ctx(clock, date(2026, 7, 2))})
    internal = SUPPORT.model_copy(update={"audience": "internal"})
    await executor.call(internal, "knowledge_search", {**SEARCH, CONTEXT_ARG: ctx(clock)})
    assert retriever.searches == 3
    clock.advance(timedelta(minutes=11))
    await executor.call(SUPPORT, "knowledge_search", {**SEARCH, CONTEXT_ARG: ctx(clock)})
    assert retriever.searches == 4
    cache.clear()
    await executor.call(SUPPORT, "knowledge_search", {**SEARCH, CONTEXT_ARG: ctx(clock)})
    assert retriever.searches == 5


async def test_only_reads_marked_cacheable_are_cached_and_failures_never_are(
    world: tuple[ToolExecutor, CountingRetriever, ReadCache, ManualClock],
) -> None:
    _, _, cache, _ = world
    cacheable = {name for name, spec in CATALOG.items() if spec.cacheable}
    assert cacheable == {
        "get_product_details",
        "get_item_details",
        "list_all_product_types",
        "knowledge_search",
        "knowledge_get_article",
    }
    assert all(CATALOG[name].effect.value == "read" for name in cacheable)
    cache.put("k", ToolResult.error("Product not found"))
    assert cache.get("k") is None

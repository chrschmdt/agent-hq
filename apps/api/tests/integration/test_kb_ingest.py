from __future__ import annotations

import secrets
from datetime import date

import pytest

from ahq.adapters.qdrant import QdrantHttp
from ahq.config import load_retrieval_config
from ahq.retrieval import (
    DENSE,
    SPARSE,
    HybridRetriever,
    Passage,
    SearchRequest,
    ServerBm25,
    collection_stats,
    day_number,
    ingest,
    load_documents,
)
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, OverlapReranker

pytestmark = pytest.mark.qdrant


async def test_hybrid_search_finds_the_current_policy(qdrant_url: str) -> None:
    store = QdrantHttp(qdrant_url)
    collection, pending = f"kb_test_{secrets.token_hex(4)}", f"kb_pending_test_{secrets.token_hex(4)}"
    embedder, sparse = HashEmbedder(), ServerBm25()
    try:
        chunks = await ingest(
            store, embedder, sparse, load_documents(REPO_ROOT / "kb"), collection=collection, pending=pending
        )
        stats = await collection_stats(store, collection)
        assert stats is not None
        assert (stats.points, stats.dense, stats.sparse) == (len(chunks), True, True)

        query = "how long do refunds to a credit card take"
        (dense,) = await embedder.embed([query], "query")
        as_of = day_number(date(2026, 6, 15))
        current = {
            "must": [
                {"key": "effective_date", "range": {"lte": as_of}},
                {"key": "valid_until", "range": {"gt": as_of}},
                {"key": "audience", "match": {"value": "customer"}},
            ]
        }
        points = await store.query(
            collection,
            {
                "prefetch": [
                    {"query": dense, "using": DENSE, "filter": current, "limit": 20},
                    {"query": sparse.query(query), "using": SPARSE, "filter": current, "limit": 20},
                ],
                "query": {"fusion": "rrf"},
                "limit": 3,
                "with_payload": True,
            },
        )
        top = [point["payload"] for point in points]
        assert top[0]["doc_id"] == "policy-refunds"
        assert all(payload["version"] == 1 for payload in top if payload["doc_id"] == "policy-returns")
    finally:
        for name in (collection, pending):
            await store.delete_collection(name)
        await store.close()


def tie_groups(passages: list[Passage]) -> list[tuple[float, frozenset[str]]]:
    groups: dict[float, set[str]] = {}
    for passage in passages:
        groups.setdefault(round(passage.score, 6), set()).add(passage.passage_id)
    return [(score, frozenset(ids)) for score, ids in groups.items()]


async def test_local_fusion_matches_qdrants(qdrant_url: str) -> None:
    store = QdrantHttp(qdrant_url)
    collection, pending = f"kb_test_{secrets.token_hex(4)}", f"kb_pending_test_{secrets.token_hex(4)}"
    embedder = HashEmbedder()
    try:
        await ingest(
            store, embedder, ServerBm25(), load_documents(REPO_ROOT / "kb"), collection=collection, pending=pending
        )
        retriever = HybridRetriever(
            store, embedder, OverlapReranker(), ServerBm25(), load_retrieval_config(), collection=collection
        )
        for query in ("refund to a gift card", "my parcel is late", "clicky keyboard switches", "cancel an order"):
            request = SearchRequest(query=query, as_of=date(2026, 6, 15), k=20, mode="hybrid")
            server = tie_groups((await retriever.search(request)).passages)
            local = tie_groups((await retriever.search(request, trace=True)).passages)
            assert server[:-1] == local[:-1], query
    finally:
        for name in (collection, pending):
            await store.delete_collection(name)
        await store.close()

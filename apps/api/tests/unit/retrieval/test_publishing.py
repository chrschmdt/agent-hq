from __future__ import annotations

from datetime import date

from ahq.config import load_retrieval_config
from ahq.ports import Json
from ahq.retrieval import (
    KB,
    KB_PENDING,
    SPARSE,
    HybridRetriever,
    KbDocument,
    KnowledgeBase,
    SearchRequest,
    ingest,
    load_documents,
)
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse, OverlapReranker
from ahq.testing.qdrant import LocalVectorStore

DRAFT = KbDocument(
    doc_id="policy-returns",
    title="Returning items",
    namespace="policy",
    audience="customer",
    version=3,
    effective_date=date(2026, 8, 1),
    source="draft:drf_1",
    body="# Returning items\n\nZebra returns are accepted for sixty days.\n\n## Window\n\nSixty zebra days.",
)


async def test_a_draft_is_invisible_until_published_and_history_stays_searchable() -> None:
    store, embedder, sparse = LocalVectorStore(), HashEmbedder(), HashingSparse()
    await ingest(store, embedder, sparse, load_documents(REPO_ROOT / "kb"))
    kb = KnowledgeBase(store, embedder, sparse)
    retriever = HybridRetriever(store, embedder, OverlapReranker(), sparse, load_retrieval_config())

    async def versions(day: date) -> set[int]:
        request = SearchRequest(query="zebra returned items window days", as_of=day, namespaces=("policy",), k=10)
        passages = (await retriever.search(request)).passages
        return {p.version for p in passages if p.doc_id == "policy-returns"}

    assert await kb.next_version("policy-returns") == 3
    await kb.stage(DRAFT)
    assert await store.count(KB_PENDING) == 2
    assert await versions(date(2026, 8, 15)) == {2}

    await kb.publish(DRAFT, date(2026, 8, 1))
    assert await store.count(KB_PENDING) == 0
    assert await versions(date(2026, 8, 15)) == {3}
    assert await versions(date(2026, 7, 15)) == {2}
    assert await versions(date(2026, 6, 15)) == {1}
    recent = await kb.versions_since(date(2026, 7, 1), date(2026, 8, 31))
    assert [(v.doc_id, v.version) for v in recent] == [("policy-returns", 3), ("policy-returns", 2)]
    assert await kb.next_version("policy-returns") == 4

    await kb.publish(DRAFT, date(2026, 8, 1))
    assert await versions(date(2026, 8, 15)) == {3}
    await store.close()


async def test_a_version_brought_forward_replaces_the_one_before_from_that_day() -> None:
    store, embedder, sparse = LocalVectorStore(), HashEmbedder(), HashingSparse()
    await ingest(store, embedder, sparse, load_documents(REPO_ROOT / "kb"))
    kb = KnowledgeBase(store, embedder, sparse)
    retriever = HybridRetriever(store, embedder, OverlapReranker(), sparse, load_retrieval_config())

    async def versions(day: date) -> set[int]:
        request = SearchRequest(query="which orders can be returned delivered", as_of=day, namespaces=("policy",), k=10)
        passages = (await retriever.search(request)).passages
        return {p.version for p in passages if p.doc_id == "policy-returns"}

    assert await versions(date(2026, 6, 15)) == {1}
    assert await kb.bring_forward("policy-returns", 2, date(2026, 6, 15))
    assert await versions(date(2026, 6, 15)) == {2}
    assert await versions(date(2026, 6, 14)) == {1}
    assert not await kb.bring_forward("policy-returns", 9, date(2026, 6, 15))
    await store.close()


async def test_restoring_the_baseline_undoes_what_was_published_and_brought_forward() -> None:
    store, embedder, sparse = LocalVectorStore(), HashEmbedder(), HashingSparse()
    kb = KnowledgeBase(store, embedder, sparse)
    assert await kb.restore() is None

    async def points() -> dict[str, tuple[Json, list[int]]]:
        found = await store.query(KB, {"limit": 1000, "with_payload": True, "with_vector": True})
        return {str(point["id"]): (point["payload"], point["vector"][SPARSE]["indices"]) for point in found}

    chunks = await ingest(store, embedder, sparse, load_documents(REPO_ROOT / "kb"))
    filed = await points()
    assert len(filed) == len(chunks)

    await kb.publish(DRAFT, date(2026, 8, 1))
    assert await kb.bring_forward("policy-returns", 2, date(2026, 6, 20))
    await kb.stage(DRAFT.model_copy(update={"version": 4}))
    assert await points() != filed

    assert await kb.restore() == len(chunks)
    assert await points() == filed
    assert await store.count(KB_PENDING) == 0
    assert await kb.next_version("policy-returns") == 3

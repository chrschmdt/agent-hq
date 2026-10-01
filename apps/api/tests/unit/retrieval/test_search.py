from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ahq.config import load_retrieval_config
from ahq.retrieval import (
    HybridRetriever,
    Passage,
    SearchRequest,
    build_filter,
    check_citations,
    ingest,
    load_documents,
    passage_id,
    rrf,
    validity,
)
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse, OverlapReranker
from ahq.testing.qdrant import LocalVectorStore

JUNE, JULY = date(2026, 6, 15), date(2026, 7, 15)


def test_rrf_scores_by_rank_and_breaks_ties_by_first_appearance() -> None:
    fused = rrf([["a", "b", "c"], ["b", "d"]], k=60)
    assert [r.passage_id for r in fused] == ["b", "a", "d", "c"]
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 60)
    assert fused[1].score == pytest.approx(1 / 60)
    assert [r.passage_id for r in rrf([["x"], ["y"]])] == ["x", "y"]


@given(st.lists(st.lists(st.sampled_from("abcdefgh"), unique=True), max_size=4))
def test_rrf_keeps_every_id_once_best_first(rankings: list[list[str]]) -> None:
    fused = rrf(rankings)
    assert sorted(r.passage_id for r in fused) == sorted({item for ranking in rankings for item in ranking})
    assert [r.score for r in fused] == sorted((r.score for r in fused), reverse=True)


def test_the_filter_keeps_versions_in_effect_for_the_audience() -> None:
    assert build_filter(JUNE, "internal") == {
        "must": [
            {"key": "effective_date", "range": {"lte": 20260615}},
            {"key": "valid_until", "range": {"gt": 20260615}},
        ]
    }
    customer = build_filter(JUNE, "customer", ("policy", "shipping"))["must"]
    assert {"key": "audience", "match": {"value": "customer"}} in customer
    assert {"key": "namespace", "match": {"any": ["policy", "shipping"]}} in customer


def passage(doc_id: str, version: int, effective: date, until: date) -> Passage:
    return Passage(
        passage_id=passage_id(doc_id, version, 0),
        doc_id=doc_id,
        title="Returning items",
        section="Overview",
        namespace="policy",
        version=version,
        effective_date=effective,
        valid_until=until,
        text="...",
        score=1.0,
    )


def test_citations_must_be_retrieved_and_in_effect() -> None:
    old = passage("policy-returns", 1, date(2026, 1, 1), date(2026, 7, 1))
    retrieved = validity([old])
    assert passage_id("policy-returns", 1, 0) == "policy-returns@v1#0"
    assert check_citations([old.passage_id], retrieved, JUNE) == []
    problems = check_citations([old.passage_id, "policy-returns@v9#0", old.passage_id], retrieved, JULY)
    assert [(p.passage_id, p.problem) for p in problems] == [
        ("policy-returns@v1#0", "not_in_effect"),
        ("policy-returns@v9#0", "not_retrieved"),
    ]


@pytest.fixture
async def retriever() -> AsyncIterator[HybridRetriever]:
    store, embedder = LocalVectorStore(), HashEmbedder()
    await ingest(store, embedder, HashingSparse(), load_documents(REPO_ROOT / "kb"))
    yield HybridRetriever(store, embedder, OverlapReranker(), HashingSparse(), load_retrieval_config())
    await store.close()


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid", "hybrid_rerank"])
async def test_every_mode_returns_k_passages(retriever: HybridRetriever, mode: str) -> None:
    request = SearchRequest.model_validate({"query": "refund to a gift card", "as_of": JUNE, "k": 4, "mode": mode})
    result = await retriever.search(request)
    assert result.mode == mode
    assert len(result.passages) == 4
    assert len({p.passage_id for p in result.passages}) == 4


async def test_a_search_sees_only_the_version_in_effect(retriever: HybridRetriever) -> None:
    query = "how many days after delivery can I return an item"
    before = await retriever.search(SearchRequest(query=query, as_of=JUNE, namespaces=("policy",), k=10))
    after = await retriever.search(SearchRequest(query=query, as_of=JULY, namespaces=("policy",), k=10))
    assert {p.version for p in before.passages if p.doc_id == "policy-returns"} == {1}
    assert {p.version for p in after.passages if p.doc_id == "policy-returns"} == {2}


async def test_customers_never_see_internal_runbooks(retriever: HybridRetriever) -> None:
    query = "runbook for a carrier delay incident"
    customer = await retriever.search(SearchRequest(query=query, as_of=JUNE, k=10))
    internal = await retriever.search(SearchRequest(query=query, as_of=JUNE, audience="internal", k=10))
    assert "runbooks" not in {p.namespace for p in customer.passages}
    assert "runbooks" in {p.namespace for p in internal.passages}


async def test_a_trace_shows_every_stage(retriever: HybridRetriever) -> None:
    request = SearchRequest(query="exchange a delivered item", as_of=JUNE, k=5, mode="hybrid_rerank")
    result = await retriever.search(request, trace=True)
    assert result.trace is not None
    assert len(result.trace.dense) == load_retrieval_config().prefetch
    assert 0 < len(result.trace.bm25) <= len(result.trace.dense)
    assert [r.passage_id for r in result.trace.reranked][:5] == [p.passage_id for p in result.passages]
    assert {r.passage_id for r in result.trace.fused} >= {r.passage_id for r in result.trace.reranked}

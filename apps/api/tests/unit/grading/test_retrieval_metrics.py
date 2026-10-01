from __future__ import annotations

from math import log2

import pytest

from ahq.config import load_retrieval_config
from ahq.evals.retrieval import MODES, chart_svg, evaluate, load_questions
from ahq.grading import ndcg_at_k, recall_at_k, reciprocal_rank
from ahq.retrieval import HybridRetriever, chunk_documents, ingest, load_documents
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse, OverlapReranker
from ahq.testing.qdrant import LocalVectorStore


def test_recall_counts_relevant_passages_in_the_top_k() -> None:
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, 2) == 0.5
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, 3) == 1.0
    with pytest.raises(ValueError, match="relevant"):
        recall_at_k(["a"], set(), 1)


def test_reciprocal_rank_is_one_over_the_first_hit() -> None:
    assert reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x"], {"a"}) == 0.0


def test_ndcg_rewards_relevant_passages_near_the_top() -> None:
    assert ndcg_at_k(["a", "b"], {"a", "b"}, 10) == 1.0
    assert ndcg_at_k(["x", "a"], {"a"}, 10) == pytest.approx(1 / log2(3))
    assert ndcg_at_k(["x", "a"], {"a", "b"}, 10) == pytest.approx((1 / log2(3)) / (1 + 1 / log2(3)))


async def test_the_eval_scores_every_mode_on_the_labeled_questions() -> None:
    questions = load_questions(REPO_ROOT / "evals" / "datasets" / "retrieval_questions.jsonl")
    assert len(questions) >= 50
    store = LocalVectorStore()
    await ingest(store, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    retriever = HybridRetriever(store, HashEmbedder(), OverlapReranker(), HashingSparse(), load_retrieval_config())
    report = await evaluate(retriever, questions[:8])
    await store.close()
    assert [scores.mode for scores in report.modes] == list(MODES)
    assert all(0 <= s.ndcg_at_10 <= 1 for s in report.modes)
    assert report.best in MODES
    assert chart_svg(report).startswith("<svg")


def test_every_labeled_passage_exists_in_the_knowledge_base() -> None:
    ids = {f"{c.doc_id}@v{c.version}#{c.position}" for c in chunk_documents(load_documents(REPO_ROOT / "kb"))}
    for question in load_questions(REPO_ROOT / "evals" / "datasets" / "retrieval_questions.jsonl"):
        assert set(question.relevant) <= ids, question.id

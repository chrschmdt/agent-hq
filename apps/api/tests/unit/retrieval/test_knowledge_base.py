from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from ahq.retrieval import (
    DENSE,
    FOREVER,
    KB,
    KB_PENDING,
    chunk_documents,
    collection_stats,
    day_number,
    ingest,
    load_documents,
    parse_document,
)
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse
from ahq.testing.qdrant import LocalVectorStore

KB_DIR = REPO_ROOT / "kb"

ARTICLE = """+++
doc_id = "policy-returns"
title = "Returning items"
namespace = "policy"
audience = "customer"
version = 1
effective_date = 2026-01-01
+++

# Returning items

Delivered items can be returned.

## Where the refund goes

To the original payment method or a gift card.

## What happens next

The status changes to return requested.
"""


def test_an_article_splits_into_titled_sections() -> None:
    document = parse_document(ARTICLE, source="kb/policy/returns.md")
    chunks = chunk_documents([document])
    assert [chunk.section for chunk in chunks] == ["Overview", "Where the refund goes", "What happens next"]
    assert chunks[1].text == "Returning items > Where the refund goes\n\nTo the original payment method or a gift card."
    assert chunk_documents([document]) == chunks


def test_an_article_without_front_matter_is_rejected() -> None:
    with pytest.raises(ValueError, match="front matter"):
        parse_document("# Returning items\n", source="kb/policy/returns.md")


def test_a_version_is_valid_until_the_next_one_takes_effect() -> None:
    first = parse_document(ARTICLE, source="kb/policy/returns.md")
    second = first.model_copy(update={"version": 2, "effective_date": date(2026, 7, 1)})
    chunks = chunk_documents([first, second])
    assert {chunk.valid_until for chunk in chunks if chunk.version == 1} == {date(2026, 7, 1)}
    assert {chunk.valid_until for chunk in chunks if chunk.version == 2} == {FOREVER}
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_the_knowledge_base_in_the_repo_is_well_formed() -> None:
    documents = load_documents(KB_DIR)
    assert Counter(d.namespace for d in documents) == {
        "policy": 7,
        "help-center": 5,
        "shipping": 4,
        "product-guides": 8,
        "runbooks": 5,
    }
    assert len({(d.doc_id, d.version) for d in documents}) == len(documents)
    assert {d.audience for d in documents if d.namespace == "runbooks"} == {"internal"}
    for document in documents:
        assert chunk_documents([document]), document.source


async def test_ingest_builds_both_collections_with_both_vectors() -> None:
    store = LocalVectorStore()
    embedder = HashEmbedder()
    chunks = await ingest(store, embedder, HashingSparse(), load_documents(KB_DIR))
    kb = await collection_stats(store, KB)
    pending = await collection_stats(store, KB_PENDING)
    assert kb is not None
    assert pending is not None
    assert (kb.points, kb.dense, kb.sparse) == (len(chunks), True, True)
    assert (pending.points, pending.dense, pending.sparse) == (0, True, True)

    (query,) = await embedder.embed(["clicky switches keyboard"], "query")
    (hit,) = await store.query(KB, {"query": query, "using": DENSE, "limit": 1, "with_payload": True})
    assert hit["payload"]["doc_id"] == "guide-mechanical-keyboard"

    current = {"key": "valid_until", "range": {"gt": day_number(date(2026, 6, 15))}}
    returns = {"key": "doc_id", "match": {"value": "policy-returns"}}
    points = await store.query(KB, {"filter": {"must": [returns, current]}, "limit": 50, "with_payload": True})
    assert {point["payload"]["version"] for point in points} == {1, 2}
    await store.close()


def test_sparse_encoding_counts_words() -> None:
    encoded = HashingSparse().document("late late parcel")
    assert sorted(encoded["values"]) == [1.0, 2.0]

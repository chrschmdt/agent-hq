from __future__ import annotations

import secrets

import pytest

from ahq.app.container import make_vector_store
from ahq.retrieval import ServerBm25, collection_config
from ahq.settings import Settings
from ahq.testing import HashEmbedder
from tests.live.conftest import require

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

DOCUMENTS = [
    "Items can be returned within 30 days of delivery for a full refund.",
    "Parcelway shipments to the Northeast are delayed by two days this week.",
    "Gift cards cannot be refunded or exchanged for cash.",
]


async def test_hybrid_query_with_server_side_bm25(live_settings: Settings) -> None:
    require(live_settings.qdrant_url, "QDRANT_URL")
    store = make_vector_store(live_settings)
    embedder, sparse = HashEmbedder(dimensions=64), ServerBm25()
    collection = f"ahq_live_{secrets.token_hex(4)}"
    try:
        assert isinstance(await store.collection_names(), list)
        await store.create_collection(collection, collection_config(64))
        vectors = await embedder.embed(DOCUMENTS, "document")
        await store.upsert(
            collection,
            [
                {"id": index, "vector": {"dense": vector, "bm25": sparse.document(text)}, "payload": {"text": text}}
                for index, (text, vector) in enumerate(zip(DOCUMENTS, vectors, strict=True))
            ],
        )
        query = "Parcelway delay Northeast"
        (dense_query,) = await embedder.embed([query], "query")
        points = await store.query(
            collection,
            {
                "prefetch": [
                    {"query": dense_query, "using": "dense", "limit": 10},
                    {"query": sparse.query(query), "using": "bm25", "limit": 10},
                ],
                "query": {"fusion": "rrf"},
                "limit": 3,
                "with_payload": True,
            },
        )
        assert "Parcelway" in points[0]["payload"]["text"]
    finally:
        await store.delete_collection(collection)
        await store.close()

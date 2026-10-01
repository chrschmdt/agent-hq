from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import pytest

from ahq.adapters.qdrant import QdrantHttp
from ahq.ports import Json, VectorStore
from ahq.retrieval import collection_config
from ahq.testing import HashingSparse
from ahq.testing.qdrant import LocalVectorStore

TEXTS = {
    1: ("returns are accepted within thirty days", [1.0, 0.0, 0.0, 0.0], 99991231),
    2: ("refunds reach a credit card in five to seven days", [0.0, 1.0, 0.0, 0.0], 99991231),
    3: ("returns used to be accepted within fourteen days", [0.9, 0.1, 0.0, 0.0], 20260701),
}
CURRENT = {"must": [{"key": "valid_until", "range": {"gt": 20260715}}]}


@pytest.fixture(params=["memory", pytest.param("qdrant", marks=pytest.mark.qdrant)])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[VectorStore]:
    if request.param == "memory":
        store: VectorStore = LocalVectorStore()
    else:
        store = QdrantHttp(request.getfixturevalue("qdrant_url"))
    yield store
    await store.close()


@pytest.fixture
async def articles(store: VectorStore) -> AsyncIterator[str]:
    name = f"contract_{secrets.token_hex(4)}"
    await store.create_collection(name, collection_config(4))
    sparse = HashingSparse()
    await store.upsert(
        name,
        [
            {
                "id": point_id,
                "vector": {"dense": dense, "bm25": sparse.document(text)},
                "payload": {"text": text, "valid_until": valid_until},
            }
            for point_id, (text, dense, valid_until) in TEXTS.items()
        ],
    )
    yield name
    await store.delete_collection(name)


def ids(points: list[Json]) -> list[int]:
    return [point["id"] for point in points]


async def test_a_collection_is_created_described_and_deleted(store: VectorStore) -> None:
    name = f"contract_{secrets.token_hex(4)}"
    assert await store.collection(name) is None
    await store.create_collection(name, collection_config(4))
    await store.create_payload_index(name, "valid_until", "integer")
    info = await store.collection(name)
    assert info is not None
    params = info["config"]["params"]
    assert params["vectors"]["dense"] == {"size": 4, "distance": "Cosine"}
    assert params["sparse_vectors"]["bm25"]["modifier"] == "idf"
    assert name in await store.collection_names()
    await store.delete_collection(name)
    await store.delete_collection(name)
    assert await store.collection(name) is None


async def test_upserting_an_existing_id_replaces_the_point(store: VectorStore, articles: str) -> None:
    assert await store.count(articles) == 3
    replacement = {"id": 3, "vector": {"dense": [0.0, 0.0, 1.0, 0.0]}, "payload": {"text": "replaced"}}
    await store.upsert(articles, [replacement])
    assert await store.count(articles) == 3
    (point,) = await store.query(articles, {"query": [0.0, 0.0, 1.0, 0.0], "using": "dense", "limit": 1})
    assert point["id"] == 3


async def test_a_dense_query_ranks_by_similarity_and_leaves_out_payloads_by_default(
    store: VectorStore, articles: str
) -> None:
    points = await store.query(articles, {"query": [1.0, 0.0, 0.0, 0.0], "using": "dense", "limit": 3})
    assert ids(points) == [1, 3, 2]
    assert points[0]["score"] > points[1]["score"]
    assert "payload" not in points[0]


async def test_a_filter_leaves_out_superseded_points(store: VectorStore, articles: str) -> None:
    request = {"query": [1.0, 0.0, 0.0, 0.0], "using": "dense", "filter": CURRENT, "limit": 3, "with_payload": True}
    points = await store.query(articles, request)
    assert ids(points) == [1, 2]
    assert points[0]["payload"]["text"] == TEXTS[1][0]
    assert ids(await store.query(articles, {"filter": CURRENT, "limit": 10})) == [1, 2]


async def test_a_hybrid_query_fuses_both_vectors_with_rrf(store: VectorStore, articles: str) -> None:
    query = "refunds to a credit card"
    request = {
        "prefetch": [
            {"query": [0.0, 1.0, 0.0, 0.0], "using": "dense", "limit": 3},
            {"query": HashingSparse().query(query), "using": "bm25", "limit": 3},
        ],
        "query": {"fusion": "rrf"},
        "limit": 2,
    }
    assert ids(await store.query(articles, request))[0] == 2


async def test_payloads_are_updated_and_points_deleted_by_filter(store: VectorStore, articles: str) -> None:
    await store.set_payload(articles, {"valid_until": 20260701}, {"must": [{"has_id": [1]}]})
    assert ids(await store.query(articles, {"filter": CURRENT, "limit": 10})) == [2]
    await store.delete_points(articles, {"must": [{"has_id": [2, 3]}]})
    assert await store.count(articles) == 1

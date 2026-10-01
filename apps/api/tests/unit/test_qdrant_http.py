from __future__ import annotations

import httpx
import pytest

from ahq.adapters.qdrant import QdrantHttp
from ahq.ports import VectorStoreError


def qdrant(handler: httpx.MockTransport) -> QdrantHttp:
    return QdrantHttp("https://cluster.example:6333/", "secret-key", transport=handler)


async def test_requests_carry_the_api_key_and_writes_wait_until_indexed() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": {"operation_id": 1, "status": "completed"}, "status": "ok"})

    store = qdrant(httpx.MockTransport(handle))
    await store.upsert("kb", [{"id": 1, "vector": {"dense": [1.0]}}])
    (request,) = seen
    assert request.headers["api-key"] == "secret-key"
    assert request.url.path == "/collections/kb/points"
    assert request.url.params["wait"] == "true"
    await store.close()


async def test_a_missing_collection_is_none_and_deleting_it_does_nothing() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": {"error": "Not found: Collection `kb` doesn't exist!"}})

    store = qdrant(httpx.MockTransport(handle))
    assert await store.collection("kb") is None
    await store.delete_collection("kb")
    await store.close()


async def test_qdrant_errors_surface_with_their_message() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"status": {"error": "Wrong input: Vector dimension error"}})

    store = qdrant(httpx.MockTransport(handle))
    with pytest.raises(VectorStoreError, match="400 Wrong input: Vector dimension error"):
        await store.query("kb", {"query": [1.0], "using": "dense"})
    await store.close()


async def test_an_unreachable_server_is_a_vector_store_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    store = qdrant(httpx.MockTransport(handle))
    with pytest.raises(VectorStoreError, match="GET /collections"):
        await store.collection_names()
    await store.close()

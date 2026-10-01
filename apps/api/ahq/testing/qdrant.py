from __future__ import annotations

import warnings
from collections.abc import Sequence

from qdrant_client import AsyncQdrantClient, models

from ahq.ports.vector_store import Json


class LocalVectorStore:
    def __init__(self) -> None:
        self._client = AsyncQdrantClient(location=":memory:")

    async def collection_names(self) -> list[str]:
        response = await self._client.get_collections()
        return [collection.name for collection in response.collections]

    async def collection(self, name: str) -> Json | None:
        if not await self._client.collection_exists(name):
            return None
        info = await self._client.get_collection(name)
        return info.model_dump(mode="json", exclude_none=True)

    async def create_collection(self, name: str, config: Json) -> None:
        spec = models.CreateCollection.model_validate(config)
        await self._client.create_collection(
            name, vectors_config=spec.vectors, sparse_vectors_config=spec.sparse_vectors
        )

    async def delete_collection(self, name: str) -> None:
        await self._client.delete_collection(name)

    async def create_payload_index(self, name: str, field: str, schema: str) -> None:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", "Payload indexes have no effect")
            await self._client.create_payload_index(name, field, models.PayloadSchemaType(schema), wait=True)

    async def upsert(self, name: str, points: Sequence[Json]) -> None:
        await self._client.upsert(name, [models.PointStruct.model_validate(point) for point in points], wait=True)

    async def set_payload(self, name: str, payload: Json, where: Json) -> None:
        selector = models.FilterSelector(filter=models.Filter.model_validate(where))
        await self._client.set_payload(name, payload=payload, points=selector, wait=True)

    async def delete_points(self, name: str, where: Json) -> None:
        selector = models.FilterSelector(filter=models.Filter.model_validate(where))
        await self._client.delete(name, points_selector=selector, wait=True)

    async def count(self, name: str) -> int:
        return (await self._client.count(name, exact=True)).count

    async def query(self, name: str, request: Json) -> list[Json]:
        spec = models.QueryRequest.model_validate(request)
        response = await self._client.query_points(
            name,
            query=spec.query,
            using=spec.using,
            prefetch=spec.prefetch,
            query_filter=spec.filter,
            limit=spec.limit or 10,
            offset=spec.offset,
            score_threshold=spec.score_threshold,
            with_payload=spec.with_payload or False,
            with_vectors=spec.with_vector or False,
        )
        return [point.model_dump(mode="json", exclude_none=True) for point in response.points]

    async def close(self) -> None:
        await self._client.close()

from __future__ import annotations

from datetime import date

from ahq.ports import Embedder, Json, VectorStore
from ahq.retrieval.chunking import chunk_documents
from ahq.retrieval.citations import passage_id
from ahq.retrieval.ingest import (
    DENSE,
    KB,
    KB_BASELINE,
    KB_PENDING,
    SPARSE,
    chunk_payload,
    day_number,
    from_day_number,
    restore_baseline,
)
from ahq.retrieval.sparse import SparseEncoder
from ahq.retrieval.types import Chunk, KbDocument, VersionInEffect


class KnowledgeBase:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        sparse: SparseEncoder,
        *,
        collection: str = KB,
        pending: str = KB_PENDING,
        baseline: str = KB_BASELINE,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._sparse = sparse
        self._collection = collection
        self._pending = pending
        self._baseline = baseline

    async def stage(self, document: KbDocument) -> list[Chunk]:
        chunks = chunk_documents([document])
        await self._upsert(self._pending, chunks)
        return chunks

    async def publish(self, document: KbDocument, day: date) -> list[Chunk]:
        effective = document.model_copy(update={"effective_date": day})
        current = {
            "must": [
                {"key": "doc_id", "match": {"value": document.doc_id}},
                {"key": "valid_until", "range": {"gt": day_number(day)}},
            ],
            "must_not": [{"key": "version", "match": {"value": document.version}}],
        }
        await self._store.set_payload(self._collection, {"valid_until": day_number(day)}, current)
        chunks = chunk_documents([effective])
        await self._upsert(self._collection, chunks)
        await self._store.delete_points(self._pending, _version_filter(document))
        return chunks

    async def bring_forward(self, doc_id: str, version: int, day: date) -> bool:
        where = {
            "must": [
                {"key": "doc_id", "match": {"value": doc_id}},
                {"key": "version", "match": {"value": version}},
            ]
        }
        if not await self._store.query(self._collection, {"filter": where, "limit": 1, "with_payload": False}):
            return False
        await self._store.set_payload(self._collection, {"effective_date": day_number(day)}, where)
        earlier = {
            "must": [
                {"key": "doc_id", "match": {"value": doc_id}},
                {"key": "version", "range": {"lt": version}},
                {"key": "valid_until", "range": {"gt": day_number(day)}},
            ]
        }
        await self._store.set_payload(self._collection, {"valid_until": day_number(day)}, earlier)
        return True

    async def restore(self) -> int | None:
        return await restore_baseline(
            self._store, collection=self._collection, baseline=self._baseline, pending=self._pending
        )

    async def discard(self, document: KbDocument) -> None:
        await self._store.delete_points(self._pending, _version_filter(document))

    async def versions_since(self, since: date, until: date) -> list[VersionInEffect]:
        where = {"must": [{"key": "effective_date", "range": {"gte": day_number(since), "lte": day_number(until)}}]}
        points = await self._store.query(self._collection, {"filter": where, "limit": 500, "with_payload": True})
        seen: dict[tuple[str, int], VersionInEffect] = {}
        for point in points:
            payload: Json = point["payload"]
            key = (str(payload["doc_id"]), int(payload["version"]))
            seen.setdefault(
                key,
                VersionInEffect(
                    doc_id=key[0],
                    version=key[1],
                    title=str(payload["title"]),
                    namespace=payload["namespace"],
                    effective_date=from_day_number(int(payload["effective_date"])),
                    first_passage=passage_id(key[0], key[1], 0),
                ),
            )
        return sorted(seen.values(), key=lambda v: (v.effective_date, v.doc_id), reverse=True)

    async def next_version(self, doc_id: str) -> int:
        where = {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}
        versions = [
            int(point["payload"]["version"])
            for name in (self._collection, self._pending)
            for point in await self._store.query(name, {"filter": where, "limit": 200, "with_payload": True})
        ]
        return max(versions, default=0) + 1

    async def _upsert(self, collection: str, chunks: list[Chunk]) -> None:
        vectors = await self._embedder.embed([chunk.text for chunk in chunks], "document")
        points: list[Json] = [
            {
                "id": chunk.chunk_id,
                "vector": {DENSE: vector, SPARSE: self._sparse.document(chunk.text)},
                "payload": chunk_payload(chunk),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self._store.upsert(collection, points)


def _version_filter(document: KbDocument) -> Json:
    return {
        "must": [
            {"key": "doc_id", "match": {"value": document.doc_id}},
            {"key": "version", "match": {"value": document.version}},
        ]
    }

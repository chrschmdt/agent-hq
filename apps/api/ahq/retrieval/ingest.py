from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ahq.ports import Embedder, Json, VectorStore
from ahq.retrieval.chunking import chunk_documents
from ahq.retrieval.sparse import SparseEncoder
from ahq.retrieval.types import Chunk, CollectionStats, KbDocument

KB = "kb"
KB_PENDING = "kb_pending"
KB_BASELINE = "kb_baseline"
DENSE = "dense"
SPARSE = "bm25"
UPSERT_BATCH = 64
PAYLOAD_INDEXES = {
    "doc_id": "keyword",
    "namespace": "keyword",
    "audience": "keyword",
    "effective_date": "integer",
    "valid_until": "integer",
    "version": "integer",
}


def day_number(value: date) -> int:
    return value.year * 10_000 + value.month * 100 + value.day


def from_day_number(day: int) -> date:
    return date(day // 10_000, day // 100 % 100, day % 100)


def chunk_payload(chunk: Chunk) -> Json:
    payload = chunk.model_dump(mode="json", exclude={"chunk_id"})
    payload["effective_date"] = day_number(chunk.effective_date)
    payload["valid_until"] = day_number(chunk.valid_until)
    return payload


def collection_config(dimensions: int) -> Json:
    return {
        "vectors": {DENSE: {"size": dimensions, "distance": "Cosine"}},
        "sparse_vectors": {SPARSE: {"modifier": "idf"}},
    }


async def ensure_collection(store: VectorStore, name: str, dimensions: int, *, recreate: bool = False) -> None:
    exists = await store.collection(name) is not None
    if exists and recreate:
        await store.delete_collection(name)
        exists = False
    if not exists:
        await store.create_collection(name, collection_config(dimensions))
    for field, schema in PAYLOAD_INDEXES.items():
        await store.create_payload_index(name, field, schema)


async def ingest(
    store: VectorStore,
    embedder: Embedder,
    sparse: SparseEncoder,
    documents: Iterable[KbDocument],
    *,
    collection: str = KB,
    pending: str = KB_PENDING,
    baseline: str | None = KB_BASELINE,
) -> list[Chunk]:
    chunks = chunk_documents(documents)
    await ensure_collection(store, pending, embedder.dimensions)
    vectors = await embedder.embed([chunk.text for chunk in chunks], "document")
    points: list[Json] = [
        {
            "id": chunk.chunk_id,
            "vector": {DENSE: vector, SPARSE: sparse.document(chunk.text)},
            "payload": chunk_payload(chunk),
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    for name in (collection, baseline):
        if name is not None:
            await _fill(store, name, embedder.dimensions, points)
    return chunks


async def restore_baseline(
    store: VectorStore, *, collection: str = KB, baseline: str = KB_BASELINE, pending: str = KB_PENDING
) -> int | None:
    info = await store.collection(baseline)
    if info is None:
        return None
    dimensions = int(info["config"]["params"]["vectors"][DENSE]["size"])
    points: list[Json] = []
    while page := await store.query(
        baseline, {"limit": UPSERT_BATCH, "offset": len(points), "with_payload": True, "with_vector": True}
    ):
        points.extend({"id": p["id"], "vector": p["vector"], "payload": p["payload"]} for p in page)
        if len(page) < UPSERT_BATCH:
            break
    await _fill(store, collection, dimensions, points)
    await ensure_collection(store, pending, dimensions, recreate=True)
    return len(points)


async def _fill(store: VectorStore, name: str, dimensions: int, points: list[Json]) -> None:
    await ensure_collection(store, name, dimensions, recreate=True)
    for start in range(0, len(points), UPSERT_BATCH):
        await store.upsert(name, points[start : start + UPSERT_BATCH])


async def collection_stats(store: VectorStore, name: str) -> CollectionStats | None:
    info = await store.collection(name)
    if info is None:
        return None
    params: Json = info["config"]["params"]
    vectors: Json = params.get("vectors") or {}
    sparse: Json = params.get("sparse_vectors") or {}
    return CollectionStats(
        name=name,
        points=await store.count(name),
        dense=DENSE in vectors,
        sparse=SPARSE in sparse,
    )

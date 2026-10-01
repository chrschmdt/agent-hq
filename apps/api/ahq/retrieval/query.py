from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from ahq.ports import Json
from ahq.retrieval.ingest import DENSE, SPARSE, day_number
from ahq.retrieval.sparse import SparseInput
from ahq.retrieval.types import Audience, Namespace


def build_filter(as_of: date, audience: Audience, namespaces: Sequence[Namespace] = ()) -> Json:
    day = day_number(as_of)
    must: list[Json] = [
        {"key": "effective_date", "range": {"lte": day}},
        {"key": "valid_until", "range": {"gt": day}},
    ]
    if audience == "customer":
        must.append({"key": "audience", "match": {"value": "customer"}})
    if namespaces:
        must.append({"key": "namespace", "match": {"any": list(namespaces)}})
    return {"must": must}


def dense_query(vector: Sequence[float], where: Json, limit: int) -> Json:
    return {"query": list(vector), "using": DENSE, "filter": where, "limit": limit, "with_payload": True}


def bm25_query(sparse: SparseInput, where: Json, limit: int) -> Json:
    return {"query": sparse, "using": SPARSE, "filter": where, "limit": limit, "with_payload": True}


def hybrid_query(
    vector: Sequence[float], sparse: SparseInput, where: Json, *, prefetch: int, limit: int, rrf_k: int
) -> Json:
    return {
        "prefetch": [
            {"query": list(vector), "using": DENSE, "filter": where, "limit": prefetch},
            {"query": sparse, "using": SPARSE, "filter": where, "limit": prefetch},
        ],
        "query": {"rrf": {"k": rrf_k}},
        "limit": limit,
        "with_payload": True,
    }

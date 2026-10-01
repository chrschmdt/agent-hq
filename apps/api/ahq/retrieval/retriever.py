from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from ahq.config import RetrievalConfig
from ahq.ports import Embedder, Json, Reranker, VectorStore
from ahq.retrieval.citations import passage_id
from ahq.retrieval.fusion import rrf
from ahq.retrieval.ingest import KB, from_day_number
from ahq.retrieval.query import bm25_query, build_filter, dense_query, hybrid_query
from ahq.retrieval.sparse import SparseEncoder
from ahq.retrieval.types import Audience, Passage, Ranked, RetrievalMode, RetrievalTrace, SearchRequest, SearchResult


class Retriever(Protocol):
    async def search(self, request: SearchRequest, *, trace: bool = False) -> SearchResult: ...

    async def article(self, doc_id: str, as_of: date, audience: Audience) -> list[Passage]: ...


class HybridRetriever:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        reranker: Reranker,
        sparse: SparseEncoder,
        config: RetrievalConfig,
        *,
        collection: str = KB,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._reranker = reranker
        self._sparse = sparse
        self._config = config
        self._collection = collection

    async def search(self, request: SearchRequest, *, trace: bool = False) -> SearchResult:
        mode: RetrievalMode = request.mode or self._config.mode
        if trace:
            return await self._traced(request, mode)
        where = build_filter(request.as_of, request.audience, request.namespaces)
        config, k = self._config, request.k
        match mode:
            case "dense":
                points = await self._query(dense_query(await self._vector(request.query), where, k))
            case "bm25":
                points = await self._query(bm25_query(self._sparse.query(request.query), where, k))
            case "hybrid" | "hybrid_rerank":
                limit = max(config.rerank_candidates, k) if mode == "hybrid_rerank" else k
                body = hybrid_query(
                    await self._vector(request.query),
                    self._sparse.query(request.query),
                    where,
                    prefetch=config.prefetch,
                    limit=limit,
                    rrf_k=config.rrf_k,
                )
                points = await self._query(body)
        passages = [_passage(point) for point in points]
        if mode == "hybrid_rerank":
            passages = await self._rerank(request.query, passages, k)
        return SearchResult(mode=mode, passages=passages[:k])

    async def article(self, doc_id: str, as_of: date, audience: Audience) -> list[Passage]:
        where = build_filter(as_of, audience)
        where["must"].append({"key": "doc_id", "match": {"value": doc_id}})
        points = await self._query({"filter": where, "limit": 100, "with_payload": True})
        passages = [_passage(point) for point in points]
        return sorted(passages, key=lambda passage: int(passage.passage_id.rsplit("#", 1)[1]))

    async def _traced(self, request: SearchRequest, mode: RetrievalMode) -> SearchResult:
        config, k = self._config, request.k
        where = build_filter(request.as_of, request.audience, request.namespaces)
        dense = [
            _passage(p)
            for p in await self._query(dense_query(await self._vector(request.query), where, config.prefetch))
        ]
        bm25 = [
            _passage(p)
            for p in await self._query(bm25_query(self._sparse.query(request.query), where, config.prefetch))
        ]
        by_id = {passage.passage_id: passage for passage in [*dense, *bm25]}
        fused = rrf([[p.passage_id for p in dense], [p.passage_id for p in bm25]], k=config.rrf_k)
        candidates = [by_id[ranked.passage_id].model_copy(update={"score": ranked.score}) for ranked in fused]
        reranked = await self._rerank(request.query, candidates[: max(config.rerank_candidates, k)], k)
        chosen = {"dense": dense, "bm25": bm25, "hybrid": candidates, "hybrid_rerank": reranked}[mode]
        return SearchResult(
            mode=mode,
            passages=chosen[:k],
            trace=RetrievalTrace(
                dense=_ranking(dense),
                bm25=_ranking(bm25),
                fused=fused,
                reranked=_ranking(reranked),
                candidates=list(by_id.values()),
            ),
        )

    async def _vector(self, query: str) -> list[float]:
        (vector,) = await self._embedder.embed([query], "query")
        return vector

    async def _query(self, body: Json) -> list[Json]:
        return await self._store.query(self._collection, body)

    async def _rerank(self, query: str, passages: Sequence[Passage], k: int) -> list[Passage]:
        hits = await self._reranker.rerank(query, [passage.text for passage in passages], k)
        return [passages[hit.index].model_copy(update={"score": hit.score}) for hit in hits]


def _passage(point: Json) -> Passage:
    payload: Json = point["payload"]
    return Passage(
        passage_id=passage_id(payload["doc_id"], payload["version"], payload["position"]),
        doc_id=payload["doc_id"],
        title=payload["title"],
        section=payload["section"],
        namespace=payload["namespace"],
        version=payload["version"],
        effective_date=from_day_number(payload["effective_date"]),
        valid_until=from_day_number(payload["valid_until"]),
        text=payload["text"],
        score=float(point.get("score", 0.0)),
    )


def _ranking(passages: Sequence[Passage]) -> list[Ranked]:
    return [Ranked(passage_id=passage.passage_id, score=passage.score) for passage in passages]

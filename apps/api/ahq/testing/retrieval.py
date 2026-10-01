from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence

from ahq.ports import EmbeddingKind, RerankHit
from ahq.retrieval import SparseVector

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class HashEmbedder:
    def __init__(self, dimensions: int = 1024) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str], kind: EmbeddingKind) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class HashingSparse:
    def document(self, text: str) -> SparseVector:
        return _sparse(text)

    def query(self, text: str) -> SparseVector:
        return _sparse(text)


def _sparse(text: str) -> SparseVector:
    counts: Counter[int] = Counter()
    for token in _tokens(text):
        counts[int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big")] += 1
    indices = sorted(counts)
    return SparseVector(indices=indices, values=[float(counts[index]) for index in indices])


class OverlapReranker:
    async def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[RerankHit]:
        query_words = set(_tokens(query))
        hits = [
            RerankHit(index=index, score=len(query_words & set(_tokens(document))) / (len(query_words) or 1))
            for index, document in enumerate(documents)
        ]
        return sorted(hits, key=lambda hit: (-hit.score, hit.index))[:top_n]

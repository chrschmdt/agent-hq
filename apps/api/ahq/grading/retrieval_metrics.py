from __future__ import annotations

from collections.abc import Collection, Sequence
from math import log2


def recall_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    if not relevant:
        raise ValueError("a question needs at least one relevant passage")
    return len(set(ranked[:k]) & set(relevant)) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: Collection[str]) -> float:
    return next((1.0 / rank for rank, item in enumerate(ranked, start=1) if item in relevant), 0.0)


def ndcg_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    gain = sum(1.0 / log2(rank + 1) for rank, item in enumerate(ranked[:k], start=1) if item in relevant)
    ideal = sum(1.0 / log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return gain / ideal

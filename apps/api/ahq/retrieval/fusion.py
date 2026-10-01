from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from ahq.retrieval.types import Ranked


def rrf(rankings: Sequence[Sequence[str]], k: int = 60) -> list[Ranked]:
    scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] += 1.0 / (k + rank)
            first_seen.setdefault(item, len(first_seen))
    ordered = sorted(scores, key=lambda item: (-scores[item], first_seen[item]))
    return [Ranked(passage_id=item, score=scores[item]) for item in ordered]

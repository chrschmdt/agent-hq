from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import comb


def pass_hat_k(outcomes: Mapping[str, Sequence[bool]], k: int) -> float:
    if not outcomes:
        raise ValueError("no tasks to score")
    scores: list[float] = []
    for task_id, trials in outcomes.items():
        n, c = len(trials), sum(trials)
        if n < k:
            raise ValueError(f"task {task_id} has {n} trials, fewer than k={k}")
        scores.append(comb(c, k) / comb(n, k))
    return sum(scores) / len(scores)

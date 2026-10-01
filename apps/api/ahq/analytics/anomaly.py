from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import fmean, pstdev

from ahq.analytics.types import Anomaly


def detect_anomaly(
    history: Sequence[float], value: float, *, z_threshold: float = 3.0, min_history: int = 14, min_spread: float = 0.01
) -> Anomaly | None:
    if len(history) < min_history:
        return None
    baseline = fmean(history)
    spread = max(pstdev(history), min_spread)
    z_score = (value - baseline) / spread
    if z_score < z_threshold:
        return None
    ratio = value / baseline if baseline else float("inf")
    return Anomaly(
        value=value,
        baseline=round(baseline, 4),
        spread=round(spread, 4),
        z_score=round(z_score, 2),
        ratio=round(ratio, 2),
    )


def count_excess(
    observed: int, expected: float, *, min_count: int = 4, z_threshold: float = 3.0, min_expected: float = 0.5
) -> Anomaly | None:
    if observed < min_count:
        return None
    spread = math.sqrt(max(expected, min_expected))
    z_score = (observed - expected) / spread
    if z_score < z_threshold:
        return None
    ratio = observed / expected if expected else float("inf")
    return Anomaly(
        value=float(observed),
        baseline=round(expected, 4),
        spread=round(spread, 4),
        z_score=round(z_score, 2),
        ratio=round(ratio, 2),
    )

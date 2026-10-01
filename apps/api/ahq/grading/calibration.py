from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import Field

from ahq.config import CalibrationPolicy
from ahq.domain import QALabel, ReviewRecord, StrictModel, Verdict

type Pair = tuple[Verdict, Literal["pass", "fail"]]

Z_95 = 1.959964


def wilson(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    if trials == 0:
        return 0.0, 1.0
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


class Calibration(StrictModel):
    criterion_id: str
    positives: int = Field(description="Labeled runs people passed on this criterion.")
    negatives: int = Field(description="Labeled runs people failed on this criterion.")
    true_positives: int
    true_negatives: int
    unknown: int = Field(description="Labeled runs the reviewer answered unknown; they count in neither rate.")
    tpr: float | None
    tnr: float | None
    tpr_interval: list[float] = Field(min_length=2, max_length=2, description="The rate's 95% Wilson interval.")
    tnr_interval: list[float] = Field(min_length=2, max_length=2, description="The rate's 95% Wilson interval.")
    calibrated: bool


def calibrate(criterion_id: str, pairs: Iterable[Pair], policy: CalibrationPolicy) -> Calibration:
    judged = list(pairs)
    known = [(judge, human) for judge, human in judged if judge != "unknown"]
    positives = sum(human == "pass" for _, human in known)
    negatives = sum(human == "fail" for _, human in known)
    true_positives = sum(judge == "pass" and human == "pass" for judge, human in known)
    true_negatives = sum(judge == "fail" and human == "fail" for judge, human in known)
    tpr = true_positives / positives if positives else None
    tnr = true_negatives / negatives if negatives else None
    calibrated = (
        positives >= policy.min_positive
        and negatives >= policy.min_negative
        and tpr is not None
        and tnr is not None
        and tpr >= policy.min_tpr
        and tnr >= policy.min_tnr
    )
    return Calibration(
        criterion_id=criterion_id,
        positives=positives,
        negatives=negatives,
        true_positives=true_positives,
        true_negatives=true_negatives,
        unknown=len(judged) - len(known),
        tpr=tpr,
        tnr=tnr,
        tpr_interval=list(wilson(true_positives, positives)),
        tnr_interval=list(wilson(true_negatives, negatives)),
        calibrated=calibrated,
    )


def corrected_pass_rate(observed: float, tpr: float, tnr: float) -> float | None:
    youden = tpr + tnr - 1
    if youden <= 0:
        return None
    return min(1.0, max(0.0, (observed + tnr - 1) / youden))


def pairs_by_criterion(reviews: Iterable[ReviewRecord], labels: Iterable[QALabel]) -> dict[str, list[Pair]]:
    verdicts: dict[tuple[str, str, str], Verdict] = {
        (r.work_item_id, r.agent, c.criterion_id): c.verdict for r in reviews for c in r.criteria
    }
    pairs: dict[str, list[Pair]] = {}
    for label in labels:
        judge = verdicts.get((label.work_item_id, label.agent, label.criterion_id))
        if judge is not None:
            pairs.setdefault(label.criterion_id, []).append((judge, label.verdict))
    return pairs


def drift(criterion_id: str, pairs: Sequence[Pair], policy: CalibrationPolicy) -> list[Calibration]:
    size = policy.window
    return [
        calibrate(criterion_id, pairs[start : start + size], policy) for start in range(0, len(pairs) - size + 1, size)
    ]

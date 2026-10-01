from __future__ import annotations

import statistics
from collections.abc import Collection, Mapping, Sequence

from ahq.domain import AgentRun, ReviewRecord
from ahq.grading import Calibration, corrected_pass_rate
from ahq.scorecards.definitions import LIMIT_STOPS, METRICS, REPLY_BLOCKED
from ahq.scorecards.types import CriterionScore, Metric, Scorecard, TrendPoint


def rate(key: str, successes: int, samples: int) -> Metric:
    return Metric(key=key, value=successes / samples if samples else None, samples=samples, successes=successes)


def share(key: str, part: int, whole: int, samples: int) -> Metric:
    return Metric(key=key, value=part / whole if whole else None, samples=samples)


def mean(key: str, values: Sequence[float]) -> Metric:
    return Metric(key=key, value=statistics.fmean(values) if values else None, samples=len(values))


def percentile(key: str, values: Sequence[float], q: float) -> Metric:
    if not values:
        return Metric(key=key, value=None, samples=0)
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, round(q * len(ordered) + 0.5) - 1))
    return Metric(key=key, value=ordered[rank], samples=len(ordered))


def criterion_scores(
    reviews: Sequence[ReviewRecord], calibrations: Mapping[str, Calibration], safety: Collection[str]
) -> list[CriterionScore]:
    ids = sorted({verdict.criterion_id for review in reviews for verdict in review.criteria})
    scores: list[CriterionScore] = []
    for criterion_id in ids:
        verdicts = [review.verdict(criterion_id) for review in reviews]
        passed, failed = verdicts.count("pass"), verdicts.count("fail")
        known = passed + failed
        raw = passed / known if known else None
        calibration = calibrations.get(criterion_id)
        scores.append(
            CriterionScore(
                criterion_id=criterion_id,
                reviewed=known,
                passed=passed,
                failed=failed,
                raw_pass_rate=raw,
                corrected_pass_rate=_corrected(raw, calibration),
                calibrated=calibration is not None and calibration.calibrated,
                safety=criterion_id in safety,
            )
        )
    return scores


def _corrected(raw: float | None, calibration: Calibration | None) -> float | None:
    if raw is None or calibration is None or not calibration.calibrated:
        return None
    if calibration.tpr is None or calibration.tnr is None:
        return None
    return corrected_pass_rate(raw, calibration.tpr, calibration.tnr)


def compute_scorecard(
    agent: str,
    version_id: str,
    runs: Sequence[AgentRun],
    reviews: Sequence[ReviewRecord],
    calibrations: Mapping[str, Calibration],
    safety: Collection[str] = (),
) -> Scorecard:
    finished = [run for run in runs if run.finished]
    n = len(finished)
    outcomes = [run.outcome for run in finished]
    approvals = sum(run.approvals for run in finished)
    rejected = sum(run.rejected_approvals for run in finished)
    per_turn = [run.seconds / max(run.turns, 1) for run in finished]
    criteria = criterion_scores(reviews, calibrations, safety)
    corrected = [score.corrected_pass_rate for score in criteria if score.corrected_pass_rate is not None]
    counted = sum(score.reviewed for score in criteria if score.corrected_pass_rate is not None)
    safety_scores = [score for score in criteria if score.safety]
    violations = sum(score.failed for score in safety_scores)
    safety_known = sum(score.reviewed for score in safety_scores)
    metrics = [
        Metric(key="qa_pass_rate", value=statistics.fmean(corrected) if corrected else None, samples=counted),
        rate("resolution_rate", sum(o in {"resolved", "done", "handed_off", "routed"} for o in outcomes), n),
        rate("escalation_rate", outcomes.count("escalated"), n),
        rate("error_rate", outcomes.count("failed"), n),
        rate("approval_rejection_rate", rejected, approvals),
        mean("cost_per_run", [run.cost_usd for run in finished]),
        mean("tokens_per_run", [float(run.input_tokens + run.output_tokens) for run in finished]),
        share(
            "cache_read_share",
            sum(run.cached_tokens for run in finished),
            sum(run.input_tokens for run in finished),
            n,
        ),
        percentile("latency_p50", per_turn, 0.5),
        percentile("latency_p95", per_turn, 0.95),
        rate("policy_violation_rate", violations, safety_known),
        rate("limit_stop_rate", sum(run.stop_reason in LIMIT_STOPS for run in finished), n),
        rate("reply_block_rate", sum(run.stop_reason == REPLY_BLOCKED for run in finished), n),
    ]
    assert {metric.key for metric in metrics} == METRICS.keys()
    return Scorecard(agent=agent, version_id=version_id, runs=n, metrics={m.key: m for m in metrics}, criteria=criteria)


def trend(
    agent: str,
    version_id: str,
    runs: Sequence[AgentRun],
    reviews: Sequence[ReviewRecord],
    calibrations: Mapping[str, Calibration],
    *,
    window: int,
    safety: Collection[str] = (),
) -> list[TrendPoint]:
    finished = sorted((run for run in runs if run.finished), key=lambda run: (run.updated_at, run.work_item_id))
    points: list[TrendPoint] = []
    for start in range(0, len(finished), window):
        chosen = finished[start : start + window]
        ids = {run.work_item_id for run in chosen}
        chosen_reviews = [review for review in reviews if review.work_item_id in ids]
        card = compute_scorecard(agent, version_id, chosen, chosen_reviews, calibrations, safety)
        points.append(TrendPoint(through=start + len(chosen), until=chosen[-1].updated_at, scorecard=card))
    return points

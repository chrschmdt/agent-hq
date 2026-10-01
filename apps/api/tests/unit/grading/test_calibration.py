from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ahq.config import CalibrationPolicy
from ahq.domain import CriterionVerdict, QALabel, ReviewRecord
from ahq.grading import Pair, calibrate, corrected_pass_rate, drift, pairs_by_criterion, wilson

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
POLICY = CalibrationPolicy(min_positive=4, min_negative=2, min_tpr=0.75, min_tnr=0.5, window=4)


def test_wilson_matches_known_intervals() -> None:
    low, high = wilson(8, 10)
    assert (round(low, 4), round(high, 4)) == (0.4902, 0.9433)
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson(0, 5)[0] == 0.0
    assert wilson(5, 5)[1] == 1.0


def test_rates_are_measured_on_known_verdicts_only() -> None:
    pairs: list[Pair] = [
        ("pass", "pass"),
        ("pass", "pass"),
        ("fail", "pass"),
        ("pass", "pass"),
        ("pass", "pass"),
        ("fail", "fail"),
        ("pass", "fail"),
        ("unknown", "fail"),
    ]
    result = calibrate("tone", pairs, POLICY)
    assert (result.positives, result.negatives, result.unknown) == (5, 2, 1)
    assert (result.tpr, result.tnr) == (0.8, 0.5)
    assert result.calibrated


@pytest.mark.parametrize(
    ("pairs", "why"),
    [
        ([("pass", "pass")] * 3 + [("fail", "fail")] * 2, "too few positives"),
        ([("pass", "pass")] * 5 + [("fail", "fail")], "too few negatives"),
        ([("pass", "pass")] * 5 + [("pass", "fail")] * 2, "misses every failure"),
    ],
)
def test_a_criterion_is_not_calibrated_without_enough_good_labels(pairs: list[Pair], why: str) -> None:
    assert not calibrate("tone", pairs, POLICY).calibrated, why


def test_the_correction_undoes_known_errors() -> None:
    assert corrected_pass_rate(0.9, 1.0, 1.0) == pytest.approx(0.9)
    assert corrected_pass_rate(0.8, 0.9, 0.8) == pytest.approx(0.6 / 0.7)
    assert corrected_pass_rate(0.05, 0.9, 0.9) == 0.0
    assert corrected_pass_rate(0.99, 0.9, 0.9) == 1.0
    assert corrected_pass_rate(0.5, 0.5, 0.5) is None


def review(work_item_id: str, verdict: str) -> ReviewRecord:
    return ReviewRecord(
        review_id=f"qa_{work_item_id}",
        work_item_id=work_item_id,
        agent="support",
        version_id="support@1",
        rubric="support@1",
        judge_model="gpt-6-luna",
        reason="sample",
        criteria=[CriterionVerdict(criterion_id="tone", critique="", verdict=verdict)],  # pyright: ignore[reportArgumentType]
        summary="",
        cost_usd=0.0,
        created_at=NOW,
    )


def label(work_item_id: str, verdict: str, criterion_id: str = "tone") -> QALabel:
    return QALabel(
        work_item_id=work_item_id,
        agent="support",
        criterion_id=criterion_id,
        verdict=verdict,  # pyright: ignore[reportArgumentType]
        labeled_by="admin",
        labeled_at=NOW,
    )


def test_labels_pair_with_the_reviewers_verdict_on_the_same_run() -> None:
    reviews = [review("wi_1", "pass"), review("wi_2", "fail")]
    labels = [label("wi_2", "fail"), label("wi_1", "fail"), label("wi_3", "pass"), label("wi_1", "pass", "other")]
    assert pairs_by_criterion(reviews, labels) == {"tone": [("fail", "fail"), ("pass", "fail")]}


def test_drift_measures_whole_windows_of_labels() -> None:
    agree: Pair = ("pass", "pass")
    miss: Pair = ("fail", "pass")
    pairs = [agree] * 4 + [miss] * 4 + [agree] * 3
    history = drift("tone", pairs, POLICY)
    assert [point.tpr for point in history] == [1.0, 0.0]

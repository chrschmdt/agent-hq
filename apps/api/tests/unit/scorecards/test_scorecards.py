from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from ahq.config import load_canary_config
from ahq.domain import AgentRun, CriterionVerdict, ReviewRecord, RunOutcome, VersionScore
from ahq.grading import Calibration
from ahq.scorecards import (
    METRICS,
    SCORECARD,
    Scorecard,
    bucket,
    compute_scorecard,
    decide_canary,
    in_share,
    judge_gate,
    trend,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
CONFIG = load_canary_config()


def run(
    index: int,
    outcome: RunOutcome = "resolved",
    *,
    version_id: str = "support@1",
    cost: float = 0.01,
    seconds: float = 4.0,
    turns: int = 1,
    approvals: int = 0,
    rejected: int = 0,
    stop_reason: str | None = None,
    minute: int = 0,
) -> AgentRun:
    return AgentRun(
        work_item_id=f"wi_{index}",
        agent="support",
        version_id=version_id,
        kind="ticket",
        outcome=outcome,
        turns=turns,
        model_calls=3,
        tool_calls=2,
        input_tokens=900,
        output_tokens=100,
        cost_usd=cost,
        seconds=seconds,
        approvals=approvals,
        rejected_approvals=rejected,
        stop_reason=stop_reason,
        started_at=NOW,
        updated_at=NOW + timedelta(minutes=minute),
    )


def review(index: int, **verdicts: str) -> ReviewRecord:
    return ReviewRecord(
        review_id=f"qa_{index}",
        work_item_id=f"wi_{index}",
        agent="support",
        version_id="support@1",
        rubric="support@1",
        judge_model="gpt-6-luna",
        reason="sample",
        criteria=[
            CriterionVerdict(criterion_id=key, critique="Seen.", verdict=value)  # pyright: ignore[reportArgumentType]
            for key, value in verdicts.items()
        ],
        summary="",
        cost_usd=0.0,
        created_at=NOW,
    )


def calibration(criterion_id: str, *, tpr: float, tnr: float, calibrated: bool = True) -> Calibration:
    return Calibration(
        criterion_id=criterion_id,
        positives=40,
        negatives=10,
        true_positives=round(tpr * 40),
        true_negatives=round(tnr * 10),
        unknown=0,
        tpr=tpr,
        tnr=tnr,
        tpr_interval=[0.0, 1.0],
        tnr_interval=[0.0, 1.0],
        calibrated=calibrated,
    )


def card(
    runs: list[AgentRun], reviews: list[ReviewRecord] | None = None, cal: dict[str, Calibration] | None = None
) -> Scorecard:
    return compute_scorecard("support", "support@1", runs, reviews or [], cal or {}, safety=["within_policy"])


def canary_card(
    outcomes: list[RunOutcome],
    reviews: list[ReviewRecord] | None = None,
    cal: dict[str, Calibration] | None = None,
    *,
    cost: float = 0.01,
) -> Scorecard:
    runs = [run(n, outcome, version_id="support@2", cost=cost) for n, outcome in enumerate(outcomes)]
    return compute_scorecard("support", "support@2", runs, reviews or [], cal or {}, safety=["within_policy"])


def test_buckets_are_sticky_and_split_work_evenly() -> None:
    ids = [f"wi_{n:05d}" for n in range(10_000)]
    chosen = [bucket(work_item_id, "support", 20) for work_item_id in ids]
    assert chosen == [bucket(work_item_id, "support", 20) for work_item_id in ids]
    assert abs(sum(chosen) / len(ids) - 0.20) < 0.02
    assert not any(bucket(work_item_id, "support", 0) for work_item_id in ids)
    assert all(bucket(work_item_id, "support", 100) for work_item_id in ids)


def test_buckets_differ_between_agents() -> None:
    ids = [f"wi_{n}" for n in range(1_000)]
    assert [bucket(i, "support", 50) for i in ids] != [bucket(i, "ops", 50) for i in ids]


def test_shares_sample_about_as_often_as_asked() -> None:
    picked = Counter(in_share(f"qa:support:wi_{n}", 0.2) for n in range(10_000))
    assert abs(picked[True] / 10_000 - 0.2) < 0.02


def test_every_metric_is_computed_from_finished_runs() -> None:
    runs = [
        run(1, cost=0.01, seconds=2, turns=2),
        run(2, "escalated", cost=0.03, seconds=9),
        run(3, "failed", stop_reason="daily_budget"),
        run(4, approvals=2, rejected=1),
        run(5, "waiting_customer", cost=5.0),
    ]
    scorecard = card(runs)
    assert scorecard.runs == 4
    assert set(scorecard.metrics) == {metric.key for metric in SCORECARD} == set(METRICS)
    assert scorecard.metrics["resolution_rate"].value == 0.5
    assert (scorecard.metrics["escalation_rate"].successes, scorecard.metrics["escalation_rate"].samples) == (1, 4)
    assert scorecard.value("error_rate") == 0.25
    assert scorecard.value("approval_rejection_rate") == 0.5
    assert scorecard.value("cost_per_run") == pytest.approx(0.015)
    assert scorecard.value("tokens_per_run") == 1_000
    assert scorecard.value("latency_p50") == 4.0
    assert scorecard.value("latency_p95") == 9.0
    assert scorecard.value("limit_stop_rate") == 0.25
    assert scorecard.value("qa_pass_rate") is None


def test_qa_counts_only_calibrated_criteria_corrected_for_the_reviewers_errors() -> None:
    reviews = [review(n, tone="pass", within_policy="pass" if n < 3 else "fail") for n in range(4)]
    uncalibrated = card([run(n) for n in range(4)], reviews)
    assert uncalibrated.value("qa_pass_rate") is None
    assert {c.criterion_id: c.raw_pass_rate for c in uncalibrated.criteria} == {"tone": 1.0, "within_policy": 0.75}
    assert uncalibrated.value("policy_violation_rate") == 0.25

    known = {"within_policy": calibration("within_policy", tpr=0.9, tnr=0.8)}
    calibrated = card([run(n) for n in range(4)], reviews, known)
    corrected = (0.75 + 0.8 - 1) / (0.9 + 0.8 - 1)
    assert calibrated.value("qa_pass_rate") == pytest.approx(corrected)
    assert calibrated.metrics["qa_pass_rate"].samples == 4


def test_a_canary_waits_for_enough_runs() -> None:
    canary = canary_card(["escalated"] * (CONFIG.min_runs - 1))
    assert decide_canary(canary, card([run(n) for n in range(20)]), CONFIG).action == "continue"


def test_a_canary_that_escalates_far_more_than_live_is_rolled_back() -> None:
    decision = decide_canary(canary_card(["escalated"] * CONFIG.min_runs), card([run(n) for n in range(20)]), CONFIG)
    assert decision.action == "rollback"
    assert decision.reasons == ["escalation rate 100% on the canary against 0% live"]


def test_a_canary_escalating_most_work_is_rolled_back_before_live_can_be_compared() -> None:
    canary = canary_card(["escalated"] * CONFIG.min_runs)
    decision = decide_canary(canary, card([run(n) for n in range(2)]), CONFIG)
    assert decision.reasons == ["escalation rate 100% on the canary, with too few live runs to compare"]


def test_the_ceiling_does_not_apply_once_live_can_be_compared() -> None:
    outcomes: list[RunOutcome] = ["escalated" if n < 6 else "resolved" for n in range(10)]
    live = card([run(n, "escalated" if n < 6 else "resolved") for n in range(10)])
    assert decide_canary(canary_card(outcomes), live, CONFIG).action == "continue"


def test_a_few_unlucky_canary_runs_are_not_enough_to_roll_back() -> None:
    resolved: list[RunOutcome] = ["resolved"] * (CONFIG.min_runs - 2)
    canary = canary_card(["escalated", "escalated", *resolved])
    live = card([run(n, "escalated" if n < 2 else "resolved") for n in range(20)])
    assert decide_canary(canary, live, CONFIG).action == "continue"


def test_a_canary_that_costs_too_much_more_is_rolled_back() -> None:
    canary = canary_card(["resolved"] * CONFIG.min_runs, cost=0.05)
    live = card([run(n, cost=0.01) for n in range(20)])
    assert decide_canary(canary, live, CONFIG).reasons == ["cost per run $0.0500 against $0.0100 live"]


def test_a_canary_with_a_worse_calibrated_qa_pass_rate_is_rolled_back() -> None:
    cal = {"within_policy": calibration("within_policy", tpr=1.0, tnr=1.0)}
    canary_reviews = [review(n, within_policy="fail" if n < 3 else "pass") for n in range(CONFIG.min_runs)]
    live_reviews = [review(100 + n, within_policy="pass") for n in range(10)]
    canary = canary_card(["resolved"] * CONFIG.min_runs, canary_reviews, cal)
    live = card([run(100 + n) for n in range(10)], live_reviews, cal)
    decision = decide_canary(canary, live, CONFIG)
    assert decision.action == "rollback"
    assert decision.reasons == ["QA pass rate 50% against 100% live"]


def test_a_clean_canary_is_promoted_after_enough_runs() -> None:
    canary = canary_card(["resolved"] * CONFIG.promote_after)
    assert decide_canary(canary, card([run(n) for n in range(20)]), CONFIG).action == "promote"


def test_trends_follow_windows_of_consecutive_runs() -> None:
    runs = [run(n, "escalated" if n >= 4 else "resolved", minute=n) for n in range(7)]
    points = trend("support", "support@1", runs, [], {}, window=3)
    assert [(point.through, point.scorecard.runs) for point in points] == [(3, 3), (6, 3), (7, 1)]
    assert [point.scorecard.value("escalation_rate") for point in points] == [0.0, 2 / 3, 1.0]
    assert points[-1].until == NOW + timedelta(minutes=6)


def score(version_id: str, value: float, *, cases: int = 4, cost: float = 0.04) -> VersionScore:
    return VersionScore(
        version_id=version_id, metric="pass^1", score=value, cases=cases, passed=round(value * cases), cost_usd=cost
    )


def test_the_gate_passes_a_candidate_close_to_live_at_a_similar_cost() -> None:
    assert judge_gate(score("support@2", 0.75), score("support@1", 0.8), CONFIG.gate).passed


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (score("support@2", 0.5), "pass^1 0.50 against 0.80 for the live version"),
        (score("support@2", 0.8, cost=0.2), "cost per case $0.0500 against $0.0100"),
        (score("support@2", 0.0, cases=0), "the candidate completed no cases"),
    ],
)
def test_the_gate_fails_a_worse_or_costlier_candidate(candidate: VersionScore, reason: str) -> None:
    verdict = judge_gate(candidate, score("support@1", 0.8), CONFIG.gate)
    assert (verdict.passed, verdict.reasons) == (False, [reason])

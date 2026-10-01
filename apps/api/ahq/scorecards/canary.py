from __future__ import annotations

from ahq.config import CanaryConfig, GatePolicy
from ahq.domain import VersionScore
from ahq.grading import wilson
from ahq.scorecards.definitions import METRICS
from ahq.scorecards.types import CanaryDecision, GateVerdict, Scorecard


def decide_canary(canary: Scorecard, live: Scorecard, config: CanaryConfig) -> CanaryDecision:
    if canary.runs < config.min_runs:
        return CanaryDecision(action="continue", reasons=[f"{canary.runs} of {config.min_runs} runs so far"])
    limits = config.rollback
    reasons = [
        reason
        for key, threshold in (
            ("escalation_rate", limits.escalation_increase),
            ("error_rate", limits.error_increase),
            ("approval_rejection_rate", limits.rejection_increase),
        )
        if (reason := _worse_rate(canary, live, key, threshold)) is not None
    ]
    reasons += [
        reason
        for key, ceiling in (("escalation_rate", limits.escalation_ceiling), ("error_rate", limits.error_ceiling))
        if (reason := _too_high(canary, live, key, ceiling)) is not None
    ]
    canary_cost, live_cost = canary.value("cost_per_run"), live.value("cost_per_run")
    if canary_cost is not None and live_cost and canary_cost / live_cost > limits.cost_ratio:
        reasons.append(f"cost per run ${canary_cost:.4f} against ${live_cost:.4f} live")
    canary_qa, live_qa = canary.value("qa_pass_rate"), live.value("qa_pass_rate")
    if canary_qa is not None and live_qa is not None and live_qa - canary_qa > limits.qa_drop:
        reasons.append(f"QA pass rate {canary_qa:.0%} against {live_qa:.0%} live")
    if reasons:
        return CanaryDecision(action="rollback", reasons=reasons)
    if canary.runs >= config.promote_after:
        return CanaryDecision(action="promote", reasons=[f"{canary.runs} runs with nothing worse than live"])
    return CanaryDecision(action="continue", reasons=[f"{canary.runs} runs, nothing worse than live so far"])


def _worse_rate(canary: Scorecard, live: Scorecard, key: str, threshold: float) -> str | None:
    mine, theirs = canary.metrics[key], live.metrics[key]
    enough = METRICS[key].min_samples
    if mine.successes is None or mine.samples < enough or theirs.value is None or theirs.samples < enough:
        return None
    low, _ = wilson(mine.successes, mine.samples)
    if low - theirs.value <= threshold:
        return None
    return f"{METRICS[key].label.lower()} {mine.value:.0%} on the canary against {theirs.value:.0%} live"


def _too_high(canary: Scorecard, live: Scorecard, key: str, ceiling: float) -> str | None:
    mine, theirs = canary.metrics[key], live.metrics[key]
    if theirs.samples >= METRICS[key].min_samples or mine.successes is None or not mine.samples:
        return None
    low, _ = wilson(mine.successes, mine.samples)
    if low <= ceiling:
        return None
    return f"{METRICS[key].label.lower()} {mine.value:.0%} on the canary, with too few live runs to compare"


def judge_gate(candidate: VersionScore, baseline: VersionScore, policy: GatePolicy) -> GateVerdict:
    reasons: list[str] = []
    if candidate.cases == 0:
        reasons.append("the candidate completed no cases")
    elif baseline.score - candidate.score > policy.score_drop:
        reasons.append(f"{candidate.metric} {candidate.score:.2f} against {baseline.score:.2f} for the live version")
    per_case = candidate.cost_usd / candidate.cases if candidate.cases else 0.0
    baseline_per_case = baseline.cost_usd / baseline.cases if baseline.cases else 0.0
    if baseline_per_case > 0 and per_case / baseline_per_case > policy.cost_ratio:
        reasons.append(f"cost per case ${per_case:.4f} against ${baseline_per_case:.4f}")
    return GateVerdict(passed=not reasons, reasons=reasons)

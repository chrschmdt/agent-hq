from __future__ import annotations

from datetime import UTC, datetime

from ahq.evals.charts import merge_trials, pass_k_svg
from ahq.evals.tau3 import Tau3Report, TrialResult

NOW = datetime(2026, 9, 27, 23, 0, tzinfo=UTC)


def report(*trials: tuple[str, int, bool]) -> Tau3Report:
    results = [
        TrialResult(
            task_id=task_id,
            trial=trial,
            reward=1.0 if passed else 0.0,
            db_match=passed,
            assertions=[],
            outcome="resolved",
            approvals=0,
            customer_turns=2,
            cost_usd=0.1,
            seconds=1.0,
        )
        for task_id, trial, passed in trials
    ]
    return Tau3Report(
        profile="medium",
        split="test",
        task_ids=sorted({t for t, _, _ in trials}),
        trials=2,
        started_at=NOW,
        results=results,
        cost_usd=0.1 * len(results),
        stopped_at_cap=False,
        patched_tasks=[],
    )


def test_trials_from_several_reports_add_up_per_task() -> None:
    first = report(("1", 0, True), ("1", 1, True), ("2", 0, True))
    gaps = report(("2", 0, False))
    assert merge_trials([first, gaps]) == {"1": [True, True], "2": [True, False]}


def test_pass_k_is_drawn_for_every_k_all_tasks_reach() -> None:
    svg = pass_k_svg({"1": [True, True], "2": [True, False]}, caption="two tasks")
    assert 'aria-label="pass^k on τ³ retail: pass^1 0.75, pass^2 0.50"' in svg
    assert "pass^3" not in svg

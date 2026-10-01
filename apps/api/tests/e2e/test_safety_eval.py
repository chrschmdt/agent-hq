from __future__ import annotations

from ahq.domain.retail import RetailSnapshot
from ahq.evals.safety import DATASET, run_safety
from ahq.grading import load_safety_cases
from tests.conftest import make_settings


async def test_the_suite_runs_offline_with_and_without_the_screen(tau3_snapshot: RetailSnapshot) -> None:
    cases = [c for c in load_safety_cases(DATASET) if c.case_id in {"kb-refund-draft", "inj-system-tag", "ctl-bot"}]
    for screen in (True, False):
        report = await run_safety(
            make_settings(tool_transport="direct"), cases, tau3_snapshot, screen=screen, max_usd=0.1
        )
        assert [r.error for r in report.results] == [None, None, None]
        assert report.summary.attacks + report.summary.not_attempted == 2
        assert report.summary.controls == 1
        assert report.screen is screen
        assert all(r.transcript[0].startswith("agent: ") for r in report.results)

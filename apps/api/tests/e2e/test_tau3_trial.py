from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from ahq.app.container import Overrides
from ahq.config import ModelRole
from ahq.domain.retail import RetailSnapshot
from ahq.evals.tau3 import run_trial
from ahq.grading import gold_hash, load_tasks
from ahq.settings import REPO_ROOT, TAU3_VERSION
from ahq.testing.rules import RuleChatModels
from tests.conftest import make_settings


class KeyLimitReached(RuleChatModels):
    def chat(self, role: ModelRole, model: str | None = None) -> BaseChatModel:
        if role == "qa":
            raise RuntimeError("Key limit exceeded (daily limit)")
        return super().chat(role, model)


async def test_a_judge_that_cannot_answer_fails_its_trial_with_the_reason(tau3_snapshot: RetailSnapshot) -> None:
    task = load_tasks(REPO_ROOT / "data" / "tau3" / TAU3_VERSION / "tasks.json")["2"]
    assert task.nl_assertions
    overrides = Overrides(
        storage="memory",
        store=tau3_snapshot,
        models=KeyLimitReached(),
        flags_start_work=False,
        review_runs=False,
    )
    result = await run_trial(
        make_settings(tool_transport="direct"), overrides, task, 0, await gold_hash(task, tau3_snapshot)
    )
    assert result.reward == 0.0
    assert result.error is not None
    assert result.error.startswith("judging failed: RuntimeError: Key limit exceeded")
    assert result.transcript

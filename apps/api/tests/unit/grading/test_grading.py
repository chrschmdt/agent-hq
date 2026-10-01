from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ahq.domain.retail import RetailSnapshot
from ahq.domain.world import TicketMessage
from ahq.grading import gold_hash, judge_assertions, load_split, load_tasks, pass_hat_k, reward, transcript_text
from ahq.testing import FakeChatModels
from tests.conftest import TAU3_DIR

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tau3" / "reference_replays.jsonl"


def test_every_task_and_split_loads() -> None:
    tasks = load_tasks(TAU3_DIR / "tasks.json")
    assert len(tasks) == 114
    assert len(load_split(TAU3_DIR / "split_tasks.json", "train")) == 74
    assert len(load_split(TAU3_DIR / "split_tasks.json", "test")) == 40
    assert sum(bool(t.nl_assertions) for t in tasks.values()) == 40
    assert tasks["0"].known_info == "You are Yusuf Rossi in zip code 19122."


@pytest.mark.parametrize("task_id", ["0", "20", "36", "100"])
async def test_the_gold_state_matches_the_recorded_answer_key(task_id: str, tau3_snapshot: RetailSnapshot) -> None:
    recorded = {row["task_id"]: row for row in map(json.loads, FIXTURES.read_text().splitlines())}
    task = load_tasks(TAU3_DIR / "tasks.json")[task_id]
    assert await gold_hash(task, tau3_snapshot) == recorded[task_id]["patched"]["final_hash"]


def test_a_task_passes_only_when_every_part_of_its_basis_passes() -> None:
    tasks = load_tasks(TAU3_DIR / "tasks.json")
    both = next(t for t in tasks.values() if t.reward_basis == ("DB", "NL_ASSERTION"))
    db_only = next(t for t in tasks.values() if t.reward_basis == ("DB",))
    assert reward(both, db_match=True, assertions_met=True) == 1.0
    assert reward(both, db_match=True, assertions_met=False) == 0.0
    assert reward(db_only, db_match=True, assertions_met=False) == 1.0
    assert reward(db_only, db_match=False, assertions_met=True) == 0.0


def test_pass_hat_k_is_the_chance_every_one_of_k_tries_succeeds() -> None:
    outcomes = {"a": [True, True, False, True], "b": [False, False, False, False], "c": [True] * 4}
    assert pass_hat_k(outcomes, 1) == pytest.approx((3 / 4 + 0 + 1) / 3)
    assert pass_hat_k(outcomes, 2) == pytest.approx((3 / 6 + 0 + 1) / 3)
    assert pass_hat_k(outcomes, 4) == pytest.approx((0 + 0 + 1) / 3)
    with pytest.raises(ValueError, match="fewer than k"):
        pass_hat_k({"a": [True]}, 2)


async def test_the_judge_grades_each_assertion_from_the_transcript() -> None:
    now = datetime(2026, 6, 15, tzinfo=UTC)
    transcript = [
        TicketMessage(author="customer", body="How many t-shirt options are there?", created_at=now),
        TicketMessage(author="agent", body="There are 10 t-shirt options.", created_at=now),
    ]
    models = FakeChatModels()
    judge = models.script(
        "qa",
        json.dumps({"results": [{"expected_outcome": "Says 10 options", "reasoning": "It does.", "met": True}]}),
    )
    verdicts, report = await judge_assertions(models, ["Says 10 options"], transcript)
    assert [v.met for v in verdicts] == [True]
    assert report is not None
    assert transcript_text(transcript) in str(judge.calls[0][-1].content)
    assert await judge_assertions(models, [], transcript) == ([], None)

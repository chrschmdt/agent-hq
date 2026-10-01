from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ahq.domain.retail import RetailSnapshot
from ahq.retail import InMemoryRetailRepo, RetailService, canonical_hash, run_action
from tests.conftest import TAU3_DIR

RECORDING = Path(__file__).parents[2] / "fixtures" / "tau3" / "reference_replays.jsonl"


def _cases() -> list[Any]:
    tasks = {task["id"]: task for task in json.loads((TAU3_DIR / "tasks.json").read_text())}
    records = [json.loads(line) for line in RECORDING.read_text().splitlines()]
    return [
        pytest.param(tasks[record["task_id"]]["evaluation_criteria"]["actions"] or [], record, id=record["task_id"])
        for record in records
    ]


CASES = _cases()


def test_the_vendored_store_hashes_like_upstream(tau3_snapshot: RetailSnapshot) -> None:
    assert canonical_hash(tau3_snapshot) == CASES[0].values[1]["initial_hash"]


@pytest.mark.parametrize(("actions", "record"), CASES)
async def test_reference_actions_match_upstream(
    tau3_snapshot: RetailSnapshot, actions: list[dict[str, Any]], record: dict[str, Any]
) -> None:
    repo = InMemoryRetailRepo(tau3_snapshot)
    service = RetailService(repo)
    outputs = [(await run_action(service, action["name"], action["arguments"])).model_dump() for action in actions]
    assert outputs == record["patched"]["outputs"]
    assert canonical_hash(await repo.snapshot()) == record["patched"]["final_hash"]


def test_the_fix_changes_only_tasks_that_swap_several_variants() -> None:
    changed = [case.id for case in CASES if case.values[1]["upstream"] != case.values[1]["patched"]]
    for case in CASES:
        if case.id in changed:
            assert any(action["name"] == "modify_pending_order_items" for action in case.values[0])
    assert len(changed) == 5

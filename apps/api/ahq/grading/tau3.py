from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ahq.domain import StrictModel
from ahq.domain.retail import RetailSnapshot
from ahq.retail import InMemoryRetailRepo, RetailService, canonical_hash, run_action

Split = Literal["train", "test", "base"]
RewardPart = Literal["DB", "NL_ASSERTION", "COMMUNICATE", "ACTION", "ENV_ASSERTION"]


class ReferenceAction(StrictModel):
    action_id: str
    name: str
    arguments: dict[str, Any]
    info: str | None = None
    compare_args: list[str] | None = None


class Tau3Task(StrictModel):
    task_id: str
    reason_for_call: str
    known_info: str | None
    unknown_info: str | None
    task_instructions: str
    persona: str | None = None
    actions: tuple[ReferenceAction, ...]
    nl_assertions: tuple[str, ...] = ()
    reward_basis: tuple[RewardPart, ...] = Field(min_length=1)


def load_tasks(tasks_json: Path) -> dict[str, Tau3Task]:
    tasks: dict[str, Tau3Task] = {}
    for raw in json.loads(tasks_json.read_text()):
        instructions = raw["user_scenario"]["instructions"]
        criteria = raw["evaluation_criteria"]
        tasks[raw["id"]] = Tau3Task(
            task_id=raw["id"],
            reason_for_call=instructions["reason_for_call"],
            known_info=instructions.get("known_info"),
            unknown_info=instructions.get("unknown_info"),
            task_instructions=instructions["task_instructions"],
            persona=raw["user_scenario"].get("persona"),
            actions=tuple(ReferenceAction.model_validate(action) for action in criteria.get("actions") or ()),
            nl_assertions=tuple(criteria.get("nl_assertions") or ()),
            reward_basis=tuple(criteria["reward_basis"]),
        )
    return tasks


def load_split(split_json: Path, split: Split) -> list[str]:
    splits: Mapping[str, list[str]] = json.loads(split_json.read_text())
    return list(splits[split])


async def gold_hash(task: Tau3Task, store: RetailSnapshot) -> str:
    repo = InMemoryRetailRepo(store)
    service = RetailService(repo)
    for action in task.actions:
        await run_action(service, action.name, action.arguments)
    return canonical_hash(await repo.snapshot())


def reward(task: Tau3Task, *, db_match: bool, assertions_met: bool) -> float:
    passed = {"DB": db_match, "NL_ASSERTION": assertions_met}
    return 1.0 if all(passed.get(part, True) for part in task.reward_basis) else 0.0

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

from pydantic import Field

from ahq.domain import StrictModel

RUBRICS_DIR = Path(__file__).resolve().parent / "rubrics"


class Criterion(StrictModel):
    id: str
    title: str
    question: str
    unknown: str = Field(description="When the reviewer should answer unknown.")
    safety: bool = False


class Rubric(StrictModel):
    agent: str
    version: int = Field(ge=1)
    criteria: tuple[Criterion, ...]

    @property
    def ref(self) -> str:
        return f"{self.agent}@{self.version}"

    def criterion(self, criterion_id: str) -> Criterion | None:
        return next((c for c in self.criteria if c.id == criterion_id), None)


@cache
def load_rubric(agent: str) -> Rubric:
    with (RUBRICS_DIR / f"{agent}.toml").open("rb") as handle:
        return Rubric.model_validate(tomllib.load(handle))


def rubric_agents() -> list[str]:
    return sorted(path.stem for path in RUBRICS_DIR.glob("*.toml"))

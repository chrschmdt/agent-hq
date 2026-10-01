from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ahq.agents.registry import SPECS
from ahq.agents.types import AgentSpec


class AgentBook(Protocol):
    async def pin(self, agent: str, work_item_id: str) -> AgentSpec: ...

    async def spec(self, version_id: str) -> AgentSpec: ...


def agent_of(version_id: str) -> str:
    return version_id.partition("@")[0]


class CodeBook:
    def __init__(self, specs: Mapping[str, AgentSpec] = SPECS) -> None:
        self._specs = dict(specs)
        self._versions = {spec.version_id: spec for spec in specs.values()}

    async def pin(self, agent: str, work_item_id: str) -> AgentSpec:
        return self._specs[agent]

    async def spec(self, version_id: str) -> AgentSpec:
        return self._versions.get(version_id) or self._specs[agent_of(version_id)]

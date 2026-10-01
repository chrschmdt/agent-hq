from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from ahq.agents.prompts import PromptTemplate
from ahq.config import ModelRole
from ahq.domain import StrictModel
from ahq.retrieval import Audience
from ahq.tools import Autonomy


class RunLimits(StrictModel):
    max_model_calls: int = Field(gt=0)
    max_usd: float = Field(gt=0)


@dataclass(frozen=True)
class AgentSpec:
    name: str
    version: int
    role: ModelRole
    prompt: PromptTemplate
    tools: tuple[str, ...]
    autonomy: Autonomy
    customer_scoped: bool
    audience: Audience
    reply: type[BaseModel]
    limits: RunLimits
    can_flag: bool = False
    checks_citations: bool = False
    model: str | None = None

    @property
    def version_id(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def channel(self) -> str:
        return f"{self.name}_messages"


class SpecProblem(StrictModel):
    spec: str
    problem: str

from __future__ import annotations

from pathlib import Path

from ahq.agents.prompts import PromptTemplate
from ahq.agents.types import AgentSpec, RunLimits
from ahq.domain import RouteDecision
from ahq.tools import Autonomy

DISPATCHER = AgentSpec(
    name="dispatcher",
    version=1,
    role="dispatcher",
    prompt=PromptTemplate.load(Path(__file__).with_name("prompt.md")),
    tools=(),
    autonomy=Autonomy.OBSERVE,
    customer_scoped=False,
    audience="internal",
    reply=RouteDecision,
    limits=RunLimits(max_model_calls=1, max_usd=0.02),
)

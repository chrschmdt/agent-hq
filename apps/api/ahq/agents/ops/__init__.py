from __future__ import annotations

from pathlib import Path

from ahq.agents.prompts import PromptTemplate
from ahq.agents.types import AgentSpec, RunLimits
from ahq.domain import IncidentReport
from ahq.tools import ANALYTICS_TOOLS, Autonomy

OPS = AgentSpec(
    name="ops",
    version=1,
    role="ops",
    prompt=PromptTemplate.load(Path(__file__).with_name("prompt.md")),
    tools=(*(tool.name for tool in ANALYTICS_TOOLS), "knowledge_search", "knowledge_get_article"),
    autonomy=Autonomy.OBSERVE,
    customer_scoped=False,
    audience="internal",
    reply=IncidentReport,
    limits=RunLimits(max_model_calls=15, max_usd=0.50),
)

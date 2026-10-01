from __future__ import annotations

from pathlib import Path

from ahq.agents.prompts import PromptTemplate
from ahq.agents.types import AgentSpec, RunLimits
from ahq.domain import SupportTurn
from ahq.tools import ORDERS_TOOLS, Autonomy

SUPPORT = AgentSpec(
    name="support",
    version=1,
    role="support",
    prompt=PromptTemplate.load(Path(__file__).with_name("prompt.md")),
    tools=(*(tool.name for tool in ORDERS_TOOLS), "knowledge_search", "knowledge_get_article"),
    autonomy=Autonomy.ACT,
    customer_scoped=True,
    audience="customer",
    reply=SupportTurn,
    limits=RunLimits(max_model_calls=25, max_usd=0.50),
    can_flag=True,
    checks_citations=True,
)

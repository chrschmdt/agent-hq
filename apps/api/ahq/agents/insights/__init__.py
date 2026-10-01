from __future__ import annotations

from pathlib import Path

from ahq.agents.prompts import PromptTemplate
from ahq.agents.types import AgentSpec, RunLimits
from ahq.domain import ProposalSet
from ahq.tools import ANALYTICS_TOOLS, Autonomy

INSIGHTS = AgentSpec(
    name="insights",
    version=1,
    role="insights",
    prompt=PromptTemplate.load(Path(__file__).with_name("prompt.md")),
    tools=(
        *(tool.name for tool in ANALYTICS_TOOLS),
        "knowledge_search",
        "knowledge_get_article",
        "knowledge_draft_article",
    ),
    autonomy=Autonomy.DRAFT,
    customer_scoped=False,
    audience="internal",
    reply=ProposalSet,
    limits=RunLimits(max_model_calls=15, max_usd=0.50),
)

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ahq.domain.base import StrictModel


class SystemPrompt(StrictModel):
    stable: str
    dynamic: str = ""

    @property
    def text(self) -> str:
        return f"{self.stable}\n\n{self.dynamic}".strip()


SupportStatus = Literal["awaiting_customer", "resolved", "transferred"]


class SupportTurn(StrictModel):
    """How Support ends a turn: its reply to the customer, the passages that back it, and where the ticket stands."""

    reply: str = Field(description="The message to the customer, in plain text.")
    citations: list[str] = Field(
        description="Ids of the knowledge base passages that back any policy stated in the reply; empty if none."
    )
    status: SupportStatus = Field(
        description=(
            "awaiting_customer while the conversation goes on, resolved when every request is handled and nothing "
            "is pending, transferred after transferring the customer to a human agent."
        )
    )
    summary: str = Field(description="One line for the operator: what the customer wants and where it stands.")


Route = Literal["support", "ops", "insights", "human"]


class RouteDecision(StrictModel):
    """Where the Dispatcher sends a piece of work, and why."""

    route: Route = Field(description="The agent that should own this work, or human for a person.")
    priority: Literal["low", "normal", "high", "urgent"]
    reason: str = Field(description="One sentence on why this route.")
    split: list[str] = Field(
        description="Separate issues found in one message, each in a few words; empty when there is only one."
    )


class Evidence(StrictModel):
    """A query and what it showed."""

    query: str = Field(description="The SQL or tool call that produced this evidence.")
    excerpt: str = Field(description="The rows or numbers that matter, briefly.")


class Affected(StrictModel):
    """What an incident touches. Unknown fields are null."""

    carrier: str | None = Field(description="Carrier id, such as northstar, or null.")
    region: str | None = Field(description="Shipping region, such as midwest, or null.")
    category: str | None = Field(description="Product category, or null.")
    item_id: str | None = Field(description="Product variant item id, or null.")
    order_ids: list[str] = Field(description="Affected order ids found so far; may be a sample.")


class IncidentReport(StrictModel):
    """How the Ops analyst ends a turn: what is wrong, the evidence, and who should act next."""

    title: str = Field(description="A short title, such as 'Northstar Post parcels late in the Midwest'.")
    summary: str
    evidence: list[Evidence]
    suspected_cause: str
    affected: Affected
    severity: Literal["low", "medium", "high"]
    recommended_action: str
    next: Literal["insights", "human", "none"] = Field(
        description="insights to propose fixes, human when a person must decide now, none if nothing more is needed."
    )
    brief: str = Field(description="What the next owner needs to know; empty when next is none.")


ProposalKind = Literal["kb_article", "policy_change", "agent_change", "operational"]


class Proposal(StrictModel):
    """One improvement Insights proposes, for a person to approve."""

    kind: ProposalKind
    title: str
    problem: str
    evidence: list[str] = Field(description="Ticket ids, incident ids, metrics or queries that show the problem.")
    proposal: str = Field(description="What to change, concretely.")
    expected_impact: str
    risk: str
    draft_id: str | None = Field(description="For a kb_article, the draft created with knowledge_draft_article.")


class ProposalSet(StrictModel):
    """How Insights ends a turn."""

    summary: str
    proposals: list[Proposal]

from __future__ import annotations

from collections.abc import Iterable

from ahq.config import ApprovalPolicy
from ahq.domain import Effect
from ahq.tools.types import (
    ActionFacts,
    Allow,
    Autonomy,
    CallContext,
    Decision,
    Deny,
    NeedsApproval,
    Principal,
    ToolSpec,
)

EFFECTS_AT: dict[Autonomy, frozenset[Effect]] = {
    Autonomy.OBSERVE: frozenset({Effect.READ}),
    Autonomy.DRAFT: frozenset({Effect.READ, Effect.GENERIC, Effect.DRAFT}),
    Autonomy.ACT: frozenset({Effect.READ, Effect.GENERIC, Effect.DRAFT, Effect.WRITE}),
}

AUTHENTICATE_FIRST = (
    "Authenticate the customer first: find their user id by email, or by first name, last name and zip code."
)
ANOTHER_CUSTOMER = "This belongs to a different customer. You can only help the customer you authenticated."


def exposed_tools(principal: Principal, catalog: Iterable[ToolSpec]) -> list[ToolSpec]:
    allowed = EFFECTS_AT[principal.autonomy]
    return [spec for spec in catalog if spec.name in principal.tools and spec.effect in allowed]


def decide(
    principal: Principal,
    spec: ToolSpec,
    facts: ActionFacts,
    context: CallContext | None,
    policy: ApprovalPolicy,
) -> Decision:
    if spec.name not in principal.tools or spec.effect not in EFFECTS_AT[principal.autonomy]:
        return Deny(reason=f"{spec.name} is not available to {principal.subject}.")
    if principal.customer_scoped and spec.customer_scoped:
        verified = context.verified_customer_id if context is not None else None
        if verified is None:
            return Deny(reason=AUTHENTICATE_FIRST)
        if facts.customer_id is not None and facts.customer_id != verified:
            return Deny(reason=ANOTHER_CUSTOMER)
    approved = context is not None and context.approval_id is not None
    if spec.exception and not approved:
        return NeedsApproval(
            reason=f"A goodwill refund of ${facts.refund_usd:.2f} is an exception to the policy.",
            refund_usd=facts.refund_usd,
        )
    if spec.refund_gated and facts.refund_usd > policy.refund_limit_usd and not approved:
        return NeedsApproval(
            reason=f"Refund of ${facts.refund_usd:.2f} is over the ${policy.refund_limit_usd:.2f} limit.",
            refund_usd=facts.refund_usd,
        )
    return Allow()

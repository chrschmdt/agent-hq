from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from ahq.config import ApprovalPolicy
from ahq.domain import Effect
from ahq.tools import (
    ANOTHER_CUSTOMER,
    AUTHENTICATE_FIRST,
    CATALOG,
    CONTEXT_ARG,
    OPERATOR,
    ActionFacts,
    Allow,
    Autonomy,
    CallContext,
    Deny,
    InvalidContext,
    NeedsApproval,
    Principal,
    decide,
    decode_context,
    encode_context,
    exposed_tools,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
POLICY = ApprovalPolicy(refund_limit_usd=100.0)
SUPPORT = Principal(
    subject="support",
    autonomy=Autonomy.ACT,
    tools=frozenset(CATALOG),
    customer_scoped=True,
    audience="customer",
)


def context(*, verified: str | None = "ada_1", approval_id: str | None = None) -> CallContext:
    return CallContext(
        work_item_id="wi_1",
        thread_id="th_wi_1",
        tool_call_id="call_1",
        subject="support",
        verified_customer_id=verified,
        approval_id=approval_id,
        as_of=date(2026, 6, 15),
        expires_at=NOW + timedelta(minutes=5),
    )


def test_each_principal_sees_the_tools_its_autonomy_allows() -> None:
    support = {spec.name for spec in exposed_tools(SUPPORT, CATALOG.values())}
    operator = {spec.name for spec in exposed_tools(OPERATOR, CATALOG.values())}
    assert support == set(CATALOG)
    assert operator == {name for name, spec in CATALOG.items() if spec.effect is Effect.READ}
    drafter = SUPPORT.model_copy(update={"autonomy": Autonomy.DRAFT})
    assert not {spec.effect for spec in exposed_tools(drafter, CATALOG.values())} & {Effect.WRITE}


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_the_permission_matrix(name: str) -> None:
    spec = CATALOG[name]
    for principal in (SUPPORT, OPERATOR):
        verdict = decide(principal, spec, ActionFacts(customer_id="ada_1"), context(), POLICY)
        visible = spec in exposed_tools(principal, CATALOG.values())
        expected = NeedsApproval if spec.exception else Allow
        assert isinstance(verdict, expected) == visible, (principal.subject, name)


def test_account_tools_need_an_authenticated_customer() -> None:
    spec = CATALOG["get_order_details"]
    unverified = decide(SUPPORT, spec, ActionFacts(customer_id="ada_1"), context(verified=None), POLICY)
    assert unverified == Deny(reason=AUTHENTICATE_FIRST)
    assert decide(SUPPORT, spec, ActionFacts(customer_id="ada_1"), None, POLICY) == Deny(reason=AUTHENTICATE_FIRST)
    other = decide(SUPPORT, spec, ActionFacts(customer_id="bob_2"), context(), POLICY)
    assert other == Deny(reason=ANOTHER_CUSTOMER)
    assert isinstance(decide(OPERATOR, spec, ActionFacts(customer_id="bob_2"), None, POLICY), Allow)


def test_lookups_and_catalog_reads_need_no_customer() -> None:
    for name in ("find_user_id_by_email", "get_product_details", "list_all_product_types", "knowledge_search"):
        assert isinstance(decide(SUPPORT, CATALOG[name], ActionFacts(), context(verified=None), POLICY), Allow)


@pytest.mark.parametrize(("refund", "needs_approval"), [(99.99, False), (100.0, False), (100.01, True)])
def test_refunds_over_the_limit_wait_for_approval(refund: float, needs_approval: bool) -> None:
    facts = ActionFacts(customer_id="ada_1", refund_usd=refund)
    verdict = decide(SUPPORT, CATALOG["return_delivered_order_items"], facts, context(), POLICY)
    assert isinstance(verdict, NeedsApproval) == needs_approval
    approved = decide(SUPPORT, CATALOG["return_delivered_order_items"], facts, context(approval_id="apv_1"), POLICY)
    assert isinstance(approved, Allow)


def test_only_money_going_back_is_gated() -> None:
    gated = {name for name, spec in CATALOG.items() if spec.refund_gated}
    assert gated == {"return_delivered_order_items", "exchange_delivered_order_items", "modify_pending_order_items"}
    assert {name for name, spec in CATALOG.items() if spec.exception} == {"issue_refund"}


@pytest.mark.parametrize("refund", [0.01, 20.0, 500.0])
def test_a_goodwill_refund_always_waits_for_approval(refund: float) -> None:
    facts = ActionFacts(customer_id="ada_1", refund_usd=refund)
    verdict = decide(SUPPORT, CATALOG["issue_refund"], facts, context(), POLICY)
    assert isinstance(verdict, NeedsApproval)
    assert verdict.refund_usd == refund
    assert isinstance(decide(SUPPORT, CATALOG["issue_refund"], facts, context(approval_id="apv_1"), POLICY), Allow)
    other = ActionFacts(customer_id="bob_2", refund_usd=refund)
    assert decide(SUPPORT, CATALOG["issue_refund"], other, context(), POLICY) == Deny(reason=ANOTHER_CUSTOMER)


def test_a_context_survives_signing_and_nothing_else_does() -> None:
    token = encode_context(context(), "key")
    assert decode_context(token, "key", NOW) == context()
    signature = token.partition(".")[2]
    forged = encode_context(context(verified="bob_2"), "key").partition(".")[0] + "." + signature
    for bad, now in ((forged, NOW), (token, NOW + timedelta(minutes=6)), (token + "x", NOW), ("garbage", NOW)):
        with pytest.raises(InvalidContext):
            decode_context(bad, "key", now)
    with pytest.raises(InvalidContext):
        decode_context(token, "another key", NOW)


def test_every_tool_is_described_in_one_to_four_sentences_without_its_context_argument() -> None:
    for name, spec in CATALOG.items():
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", spec.description) if s]
        assert 1 <= len(sentences) <= 4, name
        schema = spec.model_schema()["function"]
        assert isinstance(schema, dict)
        parameters = schema["parameters"]
        assert isinstance(parameters, dict)
        assert CONTEXT_ARG not in parameters.get("properties", {}), name  # pyright: ignore[reportOperatorIssue]

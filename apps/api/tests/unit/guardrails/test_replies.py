from __future__ import annotations

from collections.abc import Sequence

from ahq.domain import ReplyFinding
from ahq.domain.retail import Paypal, RetailSnapshot, UserName
from ahq.guardrails import Identifier, ReplyCheck, StoreOwners, find_identifiers, find_links
from ahq.retail import InMemoryRetailRepo
from tests.unit.retail.sample import ADA, ORDERS, sample_store

ADA_ORDER = "#W0000001"
GRACE_ORDER = "#W1906001"
GRACE = ADA.model_copy(
    update={
        "user_id": "grace_hopper_1906",
        "name": UserName(first_name="Grace", last_name="Hopper"),
        "address": ADA.address.model_copy(update={"address1": "9 Navy Yard Rd", "zip": "20374"}),
        "email": "grace@example.com",
        "payment_methods": {"paypal_1906": Paypal(source="paypal", id="paypal_1906")},
        "orders": [GRACE_ORDER],
    }
)


def two_customers() -> RetailSnapshot:
    store = sample_store()
    ada_order = ORDERS[0].model_copy(update={"order_id": ADA_ORDER})
    grace_order = ORDERS[0].model_copy(update={"order_id": GRACE_ORDER, "user_id": GRACE.user_id})
    return store.model_copy(
        update={
            "users": {**store.users, GRACE.user_id: GRACE},
            "orders": {**store.orders, ADA_ORDER: ada_order, GRACE_ORDER: grace_order},
        }
    )


class FixedOwners:
    def __init__(self, table: dict[str, str]) -> None:
        self.table = table
        self.asked: list[str] = []

    async def owners(self, identifiers: Sequence[Identifier]) -> dict[str, str | None]:
        self.asked += [i.value for i in identifiers]
        return {i.value: self.table.get(i.value) for i in identifiers}


def test_identifiers_are_found_once_each_in_order() -> None:
    text = f"Order {GRACE_ORDER} for grace@example.com (grace_hopper_1906); again {GRACE_ORDER} and GRACE@example.com."
    found = find_identifiers(text)
    assert [(i.kind, i.value) for i in found] == [
        ("email", "grace@example.com"),
        ("order", GRACE_ORDER),
        ("user", "grace_hopper_1906"),
    ]


def test_links_are_found_without_trailing_punctuation() -> None:
    assert find_links("See https://evil.example/c?d=ada. Or www.other.example, thanks") == [
        "https://evil.example/c?d=ada",
        "www.other.example",
    ]


async def test_another_customers_order_is_held_back_and_masked() -> None:
    check = ReplyCheck(FixedOwners({GRACE_ORDER: GRACE.user_id, ADA_ORDER: ADA.user_id}))
    reply = f"Your order {ADA_ORDER} shipped, and {GRACE_ORDER} is on its way too."
    findings = await check.check(reply, customer_id=ADA.user_id, customer_wrote="Where is my order?")
    assert findings == [ReplyFinding(kind="order", value="#W*******")]


async def test_what_the_customer_wrote_is_theirs_to_see_again() -> None:
    owners = FixedOwners({"grace@example.com": GRACE.user_id})
    check = ReplyCheck(owners)
    reply = "I could not find an account for grace@example.com. Could you check the address?"
    assert await check.check(reply, customer_id=None, customer_wrote="My email is Grace@Example.com") == []
    assert owners.asked == []


async def test_identifiers_that_belong_to_nobody_leak_nothing() -> None:
    check = ReplyCheck(FixedOwners({}))
    assert await check.check("Order #W9999999 does not exist.", customer_id=ADA.user_id, customer_wrote="") == []


async def test_an_unverified_conversation_may_not_name_anyone() -> None:
    check = ReplyCheck(FixedOwners({"grace@example.com": GRACE.user_id}))
    findings = await check.check("That is grace@example.com's account.", customer_id=None, customer_wrote="Hi")
    assert [f.kind for f in findings] == ["email"]


async def test_links_are_held_back_unless_their_host_is_allowed() -> None:
    check = ReplyCheck(FixedOwners({}), allowed_hosts=frozenset({"help.example"}))
    reply = "Read https://help.example/returns and https://docs.help.example/x, not https://evil.example/?o=1."
    findings = await check.check(reply, customer_id=None, customer_wrote="")
    assert [f.kind for f in findings] == ["link"]
    assert findings[0].value.startswith("ht")
    assert "evil" not in findings[0].value


async def test_owners_are_looked_up_in_the_store() -> None:
    owners = StoreOwners(InMemoryRetailRepo(two_customers()))
    found = await owners.owners(
        [
            Identifier("email", "GRACE@example.com"),
            Identifier("order", GRACE_ORDER),
            Identifier("order", ADA_ORDER),
            Identifier("user", GRACE.user_id),
            Identifier("order", "#W0000000"),
        ]
    )
    assert found == {
        "GRACE@example.com": GRACE.user_id,
        GRACE_ORDER: GRACE.user_id,
        ADA_ORDER: ADA.user_id,
        GRACE.user_id: GRACE.user_id,
        "#W0000000": None,
    }

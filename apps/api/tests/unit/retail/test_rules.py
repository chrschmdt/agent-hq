from __future__ import annotations

import json
import re

import pytest

from ahq.domain.retail import GiftCard, RetailSnapshot
from ahq.retail import InMemoryRetailRepo, RetailError, RetailService, run_action
from tests.unit.retail.sample import CARD, GIFT, sample_store


@pytest.fixture
def repo() -> InMemoryRetailRepo:
    return InMemoryRetailRepo(sample_store())


@pytest.fixture
def store(repo: InMemoryRetailRepo) -> RetailService:
    return RetailService(repo)


def exactly(message: str) -> str:
    return f"^{re.escape(message)}$"


def gift_balance(snapshot: RetailSnapshot) -> float:
    card = snapshot.users["ada_1"].payment_methods[GIFT]
    assert isinstance(card, GiftCard)
    return card.balance


async def test_cancelling_refunds_every_payment_and_credits_gift_cards_at_once(
    store: RetailService, repo: InMemoryRetailRepo
) -> None:
    order = await store.cancel_pending_order("#pending_gift", "no longer needed")
    assert order.status == "cancelled"
    assert order.cancel_reason == "no longer needed"
    assert [(p.transaction_type, p.amount, p.payment_method_id) for p in order.payment_history] == [
        ("payment", 50.0, GIFT),
        ("refund", 50.0, GIFT),
    ]
    assert gift_balance(await repo.snapshot()) == 150.0


async def test_only_an_exactly_pending_order_can_be_cancelled(store: RetailService) -> None:
    with pytest.raises(RetailError, match=exactly("Non-pending order cannot be cancelled")):
        await store.cancel_pending_order("#modified", "no longer needed")
    with pytest.raises(RetailError, match=exactly("Invalid reason")):
        await store.cancel_pending_order("#pending", "changed my mind")


async def test_an_item_modified_order_still_accepts_a_new_address(store: RetailService) -> None:
    order = await store.modify_pending_order_address("#modified", "2 Oak Ave", "Apt 3", "Boston", "MA", "USA", "02110")
    assert order.address.city == "Boston"
    with pytest.raises(RetailError, match=exactly("Non-pending order cannot be modified")):
        await store.modify_pending_order_address("#processed", "2 Oak Ave", "", "Boston", "MA", "USA", "02110")


async def test_swapped_items_take_their_own_variant_price_and_the_difference_is_charged(
    store: RetailService, repo: InMemoryRetailRepo
) -> None:
    order = await store.modify_pending_order_items(
        "#pending", ["mug_small", "lamp_white"], ["mug_large", "lamp_black"], GIFT
    )
    assert [(i.item_id, i.price, i.options) for i in order.items] == [
        ("mug_large", 12.5, {"size": "large"}),
        ("lamp_black", 55.0, {"color": "black"}),
    ]
    assert order.status == "pending (item modified)"
    assert order.payment_history[-1].model_dump() == {
        "transaction_type": "payment",
        "amount": 17.5,
        "payment_method_id": GIFT,
    }
    assert gift_balance(await repo.snapshot()) == 82.5


async def test_items_can_be_modified_only_once_and_only_for_available_variants_of_the_same_product(
    store: RetailService,
) -> None:
    with pytest.raises(RetailError, match=exactly("Non-pending order cannot be modified")):
        await store.modify_pending_order_items("#modified", ["mug_small"], ["mug_large"], CARD)
    with pytest.raises(RetailError, match=exactly("New item mug_gold not found or available")):
        await store.modify_pending_order_items("#pending", ["mug_small"], ["mug_gold"], CARD)
    with pytest.raises(RetailError, match=exactly("Variant not found")):
        await store.modify_pending_order_items("#pending", ["mug_small"], ["lamp_black"], CARD)
    with pytest.raises(RetailError, match=exactly("The new item id should be different from the old item id")):
        await store.modify_pending_order_items("#pending", ["mug_small"], ["mug_small"], CARD)
    with pytest.raises(RetailError, match=exactly("mug_large not found")):
        await store.modify_pending_order_items("#pending", ["mug_large"], ["mug_small"], CARD)
    with pytest.raises(RetailError, match=exactly("The number of items to be exchanged should match")):
        await store.modify_pending_order_items("#pending", ["mug_small"], [], CARD)


async def test_a_gift_card_must_cover_the_difference_and_a_failed_write_changes_nothing(
    repo: InMemoryRetailRepo,
) -> None:
    store = RetailService(repo)
    before = await repo.snapshot()
    ada = before.users["ada_1"]
    poor = ada.model_copy(
        update={"payment_methods": {**ada.payment_methods, GIFT: GiftCard(source="gift_card", id=GIFT, balance=5.0)}}
    )
    await repo.load(before.model_copy(update={"users": {"ada_1": poor}}))
    with pytest.raises(RetailError, match=exactly("Insufficient gift card balance to pay for the new item")):
        await store.modify_pending_order_items("#pending", ["lamp_white"], ["lamp_black"], GIFT)
    after = await repo.snapshot()
    assert after.orders["#pending"] == before.orders["#pending"]
    assert gift_balance(after) == 5.0


async def test_exchanges_record_the_request_with_a_rounded_difference(store: RetailService) -> None:
    with pytest.raises(RetailError, match=exactly("Non-delivered order cannot be exchanged")):
        await store.exchange_delivered_order_items("#pending", ["mug_small"], ["mug_large"], CARD)
    with pytest.raises(RetailError, match=exactly("Number of mug_small not found.")):
        await store.exchange_delivered_order_items("#delivered", ["mug_small", "mug_small"], ["mug_large"] * 2, CARD)
    order = await store.exchange_delivered_order_items(
        "#delivered", ["lamp_white", "mug_small"], ["lamp_black", "mug_large"], CARD
    )
    assert order.status == "exchange requested"
    assert order.exchange_items == ["lamp_white", "mug_small"]
    assert order.exchange_new_items == ["lamp_black", "mug_large"]
    assert order.exchange_price_difference == 17.5


async def test_returns_refund_to_the_original_method_or_a_gift_card(store: RetailService) -> None:
    order = await store.return_delivered_order_items("#delivered", ["mug_small"], GIFT)
    assert (order.status, order.return_items, order.return_payment_method_id) == (
        "return requested",
        ["mug_small"],
        GIFT,
    )


async def test_returns_to_a_card_other_than_the_original_are_refused(repo: InMemoryRetailRepo) -> None:
    before = await repo.snapshot()
    paid_by_gift = before.orders["#delivered"].model_copy(
        update={"payment_history": before.orders["#pending_gift"].payment_history}
    )
    await repo.load(before.model_copy(update={"orders": {**before.orders, "#delivered": paid_by_gift}}))
    with pytest.raises(RetailError, match=exactly("Payment method should be the original payment method")):
        await RetailService(repo).return_delivered_order_items("#delivered", ["mug_small"], CARD)


async def test_moving_a_payment_to_a_gift_card_charges_it_and_refunds_the_original(
    store: RetailService, repo: InMemoryRetailRepo
) -> None:
    order = await store.modify_pending_order_payment("#pending", GIFT)
    assert [(p.transaction_type, p.payment_method_id) for p in order.payment_history] == [
        ("payment", CARD),
        ("payment", GIFT),
        ("refund", CARD),
    ]
    assert gift_balance(await repo.snapshot()) == 50.0
    with pytest.raises(RetailError, match=exactly("There should be exactly one payment for a pending order")):
        await store.modify_pending_order_payment("#pending", CARD)


async def test_customers_are_found_by_email_ignoring_case_or_by_name_and_zip(store: RetailService) -> None:
    assert await store.find_user_id_by_email("ada@example.COM") == "ada_1"
    assert await store.find_user_id_by_name_zip("ada", "LOVELACE", "78701") == "ada_1"
    with pytest.raises(RetailError, match=exactly("User not found")):
        await store.find_user_id_by_name_zip("Ada", "Lovelace", "00000")


@pytest.mark.parametrize(
    ("expression", "output"),
    [("2 + 2", "4.0"), ("10 / 3", "3.33"), ("(1.5 + 2) * -2", "-7.0"), ("2 ** 10", "1024.0")],
)
async def test_calculate_rounds_to_cents(store: RetailService, expression: str, output: str) -> None:
    assert await store.calculate(expression) == output


async def test_tool_calls_report_errors_as_text_like_the_benchmark(store: RetailService) -> None:
    assert (await run_action(store, "calculate", {"expression": "1 / 0"})).model_dump() == {
        "output": "Error: division by zero",
        "error": True,
    }
    assert (await run_action(store, "calculate", {"expression": "import os"})).output == (
        "Error: Invalid characters in expression"
    )
    assert (await run_action(store, "get_order_details", {"order_id": "#nope"})).output == "Error: Order not found"
    assert (await run_action(store, "drop_tables", {})).output == "Error: Tool 'drop_tables' not found."
    unexpected = await run_action(store, "get_order_details", {"id": "#pending"})
    assert unexpected.error
    assert unexpected.output.startswith("Error: ")


async def test_successful_tool_calls_return_json(store: RetailService) -> None:
    listed = await run_action(store, "list_all_product_types", {})
    assert json.loads(listed.output) == {"Lamp": "p_lamp", "Mug": "p_mug"}
    details = await run_action(store, "get_item_details", {"item_id": "mug_large"})
    assert json.loads(details.output) == {
        "item_id": "mug_large",
        "options": {"size": "large"},
        "available": True,
        "price": 12.5,
    }
    assert (await run_action(store, "transfer_to_human_agents", {"summary": "wants a manager"})).output == (
        "Transfer successful"
    )


async def test_a_goodwill_refund_goes_to_the_original_payment_and_never_exceeds_what_was_paid(
    store: RetailService,
) -> None:
    order = await store.issue_refund("#delivered", 20.0, "The parcel arrived four days late.")
    assert [(p.transaction_type, p.amount, p.payment_method_id) for p in order.payment_history][-1] == (
        "refund",
        20.0,
        CARD,
    )
    assert order.status == "delivered"
    with pytest.raises(RetailError, match=exactly("Refund exceeds the 30.00 left to refund on this order")):
        await store.issue_refund("#delivered", 30.01, "The parcel arrived four days late.")
    await store.issue_refund("#processed", 50.0, "The lamp arrived scratched.")


async def test_a_goodwill_refund_to_a_gift_card_credits_it_at_once(repo: InMemoryRetailRepo) -> None:
    store = RetailService(repo)
    delivered = (await repo.snapshot()).orders["#pending_gift"].model_copy(update={"status": "delivered"})
    snapshot = await repo.snapshot()
    await repo.load(snapshot.model_copy(update={"orders": {**snapshot.orders, "#pending_gift": delivered}}))
    await store.issue_refund("#pending_gift", 10.0, "The mug arrived chipped.")
    assert gift_balance(await repo.snapshot()) == 110.0


@pytest.mark.parametrize("order_id", ["#pending", "#modified"])
async def test_pending_orders_get_no_goodwill_refund(store: RetailService, order_id: str) -> None:
    with pytest.raises(RetailError, match=exactly("Only a processed or delivered order can get a goodwill refund")):
        await store.issue_refund(order_id, 5.0, "The customer is unhappy.")

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from ahq.domain import Effect, StrictModel, ToolResult
from ahq.retail import RetailError, RetailService, run_action
from ahq.tools.types import ActionFacts, FactsFn, Handler, Invocation, ToolDeps, ToolSpec

ORDER_ID = "The order id, such as '#W0000000', with the '#' at the start."
ITEM_IDS = "Item ids, each such as '1008292230'. An item may appear more than once."
PAYMENT_METHOD_ID = (
    "A payment method id from the customer's profile, such as 'gift_card_0000000' or 'credit_card_0000000'."
)


class FindByEmail(StrictModel):
    email: str = Field(description="The customer's email, such as 'something@example.com'.")


class FindByNameZip(StrictModel):
    first_name: str = Field(description="The customer's first name, such as 'John'.")
    last_name: str = Field(description="The customer's last name, such as 'Doe'.")
    zip: str = Field(description="The customer's zip code, such as '12345'.")


class UserRef(StrictModel):
    user_id: str = Field(description="The user id, such as 'sara_doe_496'.")


class OrderRef(StrictModel):
    order_id: str = Field(description=ORDER_ID)


class ProductRef(StrictModel):
    product_id: str = Field(description="The product id, such as '6086499569'. Product ids differ from item ids.")


class ItemRef(StrictModel):
    item_id: str = Field(description="The item id, such as '6086499569'. Item ids differ from product ids.")


class NoArguments(StrictModel):
    pass


class Calculation(StrictModel):
    expression: str = Field(description="An arithmetic expression, such as '2 + 2'.")


class Cancellation(OrderRef):
    reason: Literal["no longer needed", "ordered by mistake"] = Field(description="Why the customer is cancelling.")


class AddressChange(OrderRef):
    address1: str = Field(description="The first line of the address, such as '123 Main St'.")
    address2: str = Field(description="The second line of the address, such as 'Apt 1', or ''.")
    city: str = Field(description="The city, such as 'San Francisco'.")
    state: str = Field(description="The state, such as 'CA'.")
    country: str = Field(description="The country, such as 'USA'.")
    zip: str = Field(description="The zip code, such as '12345'.")


class UserAddressChange(StrictModel):
    user_id: str = Field(description="The user id, such as 'sara_doe_496'.")
    address1: str = Field(description="The first line of the address, such as '123 Main St'.")
    address2: str = Field(description="The second line of the address, such as 'Apt 1', or ''.")
    city: str = Field(description="The city, such as 'San Francisco'.")
    state: str = Field(description="The state, such as 'CA'.")
    country: str = Field(description="The country, such as 'USA'.")
    zip: str = Field(description="The zip code, such as '12345'.")


class ItemSwap(OrderRef):
    item_ids: list[str] = Field(description=ITEM_IDS)
    new_item_ids: list[str] = Field(
        description="The new item ids, each the same product as the item in the same position of item_ids."
    )
    payment_method_id: str = Field(description=PAYMENT_METHOD_ID)


class PaymentChange(OrderRef):
    payment_method_id: str = Field(description=PAYMENT_METHOD_ID)


class ReturnRequest(OrderRef):
    item_ids: list[str] = Field(description=ITEM_IDS)
    payment_method_id: str = Field(
        description="Where the refund goes: the original payment method, or a gift card from the customer's profile."
    )


class GoodwillRefund(OrderRef):
    amount: float = Field(gt=0, description="The amount to refund, in dollars, such as 15.00.")
    reason: str = Field(min_length=10, description="Why the customer deserves it, for the person who approves it.")


class Transfer(StrictModel):
    summary: str = Field(description="A summary of the customer's issue for the person taking over.")


def _run(name: str) -> Handler:
    async def handle(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
        service = RetailService(deps.retail)
        if invocation.record is not None:
            service = service.recording(invocation.record)
        outcome = await run_action(service, name, args.model_dump())
        return ToolResult(output=outcome.output)

    return handle


async def _owner_of_user(args: BaseModel, deps: ToolDeps) -> ActionFacts:
    assert isinstance(args, UserRef | UserAddressChange)
    return ActionFacts(customer_id=args.user_id)


async def _owner_of_order(args: BaseModel, deps: ToolDeps) -> ActionFacts:
    assert isinstance(args, OrderRef)
    try:
        order = await RetailService(deps.retail).get_order_details(args.order_id)
    except RetailError:
        return ActionFacts()
    return ActionFacts(customer_id=order.user_id)


async def _refund_of_return(args: BaseModel, deps: ToolDeps) -> ActionFacts:
    assert isinstance(args, ReturnRequest)
    try:
        order = await RetailService(deps.retail).get_order_details(args.order_id)
    except RetailError:
        return ActionFacts()
    prices = {item.item_id: item.price for item in order.items}
    refund = sum(prices.get(item_id, 0.0) for item_id in args.item_ids)
    return ActionFacts(customer_id=order.user_id, refund_usd=round(refund, 2))


async def _refund_of_swap(args: BaseModel, deps: ToolDeps) -> ActionFacts:
    assert isinstance(args, ItemSwap)
    service = RetailService(deps.retail)
    try:
        order = await service.get_order_details(args.order_id)
    except RetailError:
        return ActionFacts()
    old = {item.item_id: item.price for item in order.items}
    new = await _prices(service, args.new_item_ids)
    difference = sum(old.get(item_id, 0.0) for item_id in args.item_ids) - sum(new)
    return ActionFacts(customer_id=order.user_id, refund_usd=round(max(difference, 0.0), 2))


async def _refund_of_goodwill(args: BaseModel, deps: ToolDeps) -> ActionFacts:
    assert isinstance(args, GoodwillRefund)
    facts = await _owner_of_order(args, deps)
    return facts.model_copy(update={"refund_usd": round(args.amount, 2)})


async def _prices(service: RetailService, item_ids: Sequence[str]) -> list[float]:
    prices: list[float] = []
    for item_id in item_ids:
        try:
            prices.append((await service.get_item_details(item_id)).price)
        except RetailError:
            prices.append(0.0)
    return prices


async def _track(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, OrderRef)
    try:
        order = await RetailService(deps.retail).get_order_details(args.order_id)
    except RetailError as error:
        return ToolResult.error(str(error))
    parcels: list[dict[str, str | None]] = []
    for tracking_id in (t for fulfillment in order.fulfillments for t in fulfillment.tracking_id):
        shipment = await deps.world.shipment(tracking_id) if deps.world is not None else None
        if shipment is None:
            continue
        parcels.append(
            {
                "tracking_id": shipment.tracking_id,
                "carrier": shipment.carrier,
                "status": shipment.status,
                "shipped_at": shipment.shipped_at.isoformat() if shipment.shipped_at else None,
                "due_at": shipment.promised_at.isoformat() if shipment.promised_at else None,
                "delivered_at": shipment.delivered_at.isoformat() if shipment.delivered_at else None,
            }
        )
    if not parcels:
        return ToolResult(output=f"No tracking information for order {order.order_id}.")
    return ToolResult(output=json.dumps(parcels))


def _tool(
    name: str,
    effect: Effect,
    args: type[BaseModel],
    description: str,
    *,
    handler: Handler | None = None,
    customer_scoped: bool = False,
    refund_gated: bool = False,
    exception: bool = False,
    cacheable: bool = False,
    facts: FactsFn | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        server="orders",
        effect=effect,
        description=description,
        args=args,
        handler=handler or _run(name),
        customer_scoped=customer_scoped,
        refund_gated=refund_gated,
        exception=exception,
        cacheable=cacheable,
        facts=facts,
    )


ORDERS_TOOLS: tuple[ToolSpec, ...] = (
    _tool(
        "find_user_id_by_email",
        Effect.READ,
        FindByEmail,
        "Find a customer's user id by their email address. This is how a customer is authenticated at the start of "
        "a conversation, even when they already gave their user id. Returns the user id, or an error if no customer "
        "has that email.",
    ),
    _tool(
        "find_user_id_by_name_zip",
        Effect.READ,
        FindByNameZip,
        "Find a customer's user id by first name, last name and zip code. Use it only when the customer cannot give "
        "an email, or the email lookup found nothing. Returns the user id, or an error if no customer matches.",
    ),
    _tool(
        "get_user_details",
        Effect.READ,
        UserRef,
        "Get a customer's profile: name, email, default address, payment methods and order ids. Only the "
        "authenticated customer's profile can be read.",
        customer_scoped=True,
        facts=_owner_of_user,
    ),
    _tool(
        "get_order_details",
        Effect.READ,
        OrderRef,
        "Get the status and details of an order: items, shipping address, fulfillments and payment history. Order "
        "ids start with '#', such as '#W0000000'. Only the authenticated customer's orders can be read.",
        customer_scoped=True,
        facts=_owner_of_order,
    ),
    _tool(
        "track_order",
        Effect.READ,
        OrderRef,
        "Get where each parcel of an order is, as its carrier reports it: the carrier, the status, and when it "
        "shipped, is due and was delivered. Use it when a customer asks where an order is, or when a policy depends "
        "on when an order was delivered. Only the authenticated customer's orders can be tracked.",
        handler=_track,
        customer_scoped=True,
        facts=_owner_of_order,
    ),
    _tool(
        "get_product_details",
        Effect.READ,
        ProductRef,
        "Get a product and all of its items, with each item's options, price and availability. Product ids differ "
        "from item ids. Use it to find the item a customer wants to exchange or swap to.",
        cacheable=True,
    ),
    _tool(
        "get_item_details",
        Effect.READ,
        ItemRef,
        "Get one item, a variant of a product, by its item id: its options, price and availability. Item ids differ "
        "from product ids.",
        cacheable=True,
    ),
    _tool(
        "list_all_product_types",
        Effect.READ,
        NoArguments,
        "List the store's 50 product types with their product ids, sorted by name. Each product type has several "
        "items with their own item ids and options. Use it to find the product id of a product the customer names.",
        cacheable=True,
    ),
    _tool(
        "calculate",
        Effect.GENERIC,
        Calculation,
        "Calculate the result of an arithmetic expression, such as '2 + 2'. The expression may contain numbers, "
        "+, -, *, /, parentheses and spaces. Returns the result rounded to two decimals.",
    ),
    _tool(
        "cancel_pending_order",
        Effect.WRITE,
        Cancellation,
        "Cancel a pending order; processed, delivered or cancelled orders cannot be cancelled. Explain the "
        "cancellation and get the customer's explicit confirmation (yes) first. Gift card payments are refunded "
        "at once, other payments within 5 to 7 business days.",
        customer_scoped=True,
        facts=_owner_of_order,
    ),
    _tool(
        "modify_pending_order_address",
        Effect.WRITE,
        AddressChange,
        "Change the shipping address of a pending order. Explain the change and get the customer's explicit "
        "confirmation (yes) first. Returns the order after the change.",
        customer_scoped=True,
        facts=_owner_of_order,
    ),
    _tool(
        "modify_pending_order_items",
        Effect.WRITE,
        ItemSwap,
        "Swap items in a pending order for other items of the same product, settling the price difference with a "
        "payment method. It can be done only once per order, so collect every change first. Explain the change and "
        "get the customer's explicit confirmation (yes) first.",
        customer_scoped=True,
        refund_gated=True,
        facts=_refund_of_swap,
    ),
    _tool(
        "modify_pending_order_payment",
        Effect.WRITE,
        PaymentChange,
        "Move a pending order's payment to another of the customer's payment methods. The new method must differ "
        "from the current one, and a gift card must cover the total. Explain the change and get the customer's "
        "explicit confirmation (yes) first.",
        customer_scoped=True,
        facts=_owner_of_order,
    ),
    _tool(
        "modify_user_address",
        Effect.WRITE,
        UserAddressChange,
        "Change the customer's default address. Explain the change and get the customer's explicit confirmation "
        "(yes) first. Returns the customer's profile after the change.",
        customer_scoped=True,
        facts=_owner_of_user,
    ),
    _tool(
        "return_delivered_order_items",
        Effect.WRITE,
        ReturnRequest,
        "Request a return of items from a delivered order; its status becomes 'return requested' and the customer "
        "gets an email about sending the items back. A delivered order can be returned or exchanged only once, so "
        "collect every item first. Explain the return and get the customer's explicit confirmation (yes) first.",
        customer_scoped=True,
        refund_gated=True,
        facts=_refund_of_return,
    ),
    _tool(
        "exchange_delivered_order_items",
        Effect.WRITE,
        ItemSwap,
        "Exchange items in a delivered order for other items of the same product, settling the price difference "
        "with a payment method. A delivered order can be returned or exchanged only once, so collect every item "
        "first. Explain the exchange and get the customer's explicit confirmation (yes) first.",
        customer_scoped=True,
        refund_gated=True,
        facts=_refund_of_swap,
    ),
    _tool(
        "issue_refund",
        Effect.WRITE,
        GoodwillRefund,
        "Refund part of a processed or delivered order as goodwill, to its original payment method, when the policy "
        "has no remedy but the customer's case clearly calls for one, such as a parcel that arrived days late. "
        "It runs only after a person approves it, so never promise a goodwill refund before the tool returns.",
        customer_scoped=True,
        exception=True,
        facts=_refund_of_goodwill,
    ),
    _tool(
        "transfer_to_human_agents",
        Effect.GENERIC,
        Transfer,
        "Transfer the customer to a human agent, with a summary of their issue. Transfer only if the customer asks "
        "for a person, or their issue cannot be solved with your tools within policy. Then tell the customer they "
        "are being transferred.",
    ),
)

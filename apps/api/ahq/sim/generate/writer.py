from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from langchain_core.messages import HumanMessage, SystemMessage

from ahq.config import WorldConfig
from ahq.domain import StrictModel
from ahq.domain.retail import Order, Product, RetailSnapshot, Variant
from ahq.domain.world import Shipment
from ahq.ports import ChatModels
from ahq.sim.generate.content import ReviewRecord, TicketMessageRecord, TicketRecord
from ahq.sim.seeded import rng

WRITER = "writer"
HISTORY_DAYS = 90

REVIEW_TOPICS: Mapping[str, tuple[str, ...]] = {
    "electronics": ("battery life", "sound or picture quality", "setup and pairing", "build quality", "value"),
    "home": ("noise", "build quality", "ease of cleaning", "size", "value"),
    "outdoors": ("durability", "comfort", "weight", "value"),
    "apparel": ("fit and sizing", "comfort", "material", "color"),
    "personal_care": ("scent", "battery life", "packaging"),
    "hobbies": ("quality", "difficulty", "value"),
}
RATINGS = (5, 4, 3, 2, 1)
RATING_WEIGHTS = (0.42, 0.28, 0.12, 0.08, 0.10)

TICKET_SITUATIONS: Mapping[str, str] = {
    "where_is_my_order": "The customer asks where order {order} is; the agent checks tracking and gives an estimate.",
    "return_items": "The customer returns the {product} from order {order}; the agent explains the return steps.",
    "exchange_items": "The customer wants a different option of the {product} from order {order}; the agent arranges "
    "an exchange.",
    "cancel_order": "The customer cancels order {order} because they ordered it by mistake; the agent confirms and "
    "explains the refund timing.",
    "refund_status": "The customer asks when the refund for cancelled order {order} arrives; the agent explains the "
    "timing for their payment method.",
    "product_question": "The customer asks how to use or care for the {product}; the agent answers from the product "
    "guide.",
    "damaged_item": "The {product} from order {order} arrived damaged; the agent offers a return or an exchange.",
}
TICKET_MIX: Mapping[str, float] = {
    "where_is_my_order": 0.22,
    "return_items": 0.18,
    "exchange_items": 0.12,
    "cancel_order": 0.12,
    "refund_status": 0.12,
    "product_question": 0.16,
    "damaged_item": 0.08,
}

SYSTEM = """You write realistic content for an online store's history: product reviews and support conversations.

Rules:
- Plain, natural language, like real customers and support agents. Vary tone and length.
- Put each seed's topic or situation in the writer's own words. Customers describing the same problem never share
  phrasing, and none of them repeats the seed's wording.
- No em dashes, no en dashes, no emojis, no markdown.
- Use only the facts you are given. Do not invent order numbers, prices or policies.
- Store policy, when it comes up: returns and exchanges are for delivered orders; refunds go to the original payment
  method or a gift card; gift card refunds are immediate, card and PayPal refunds take 5 to 7 business days.
- Return exactly one item per seed, with the seed's id."""


class WrittenReview(StrictModel):
    review_id: str
    title: str
    body: str


class ReviewBatch(StrictModel):
    reviews: list[WrittenReview]


class WrittenMessage(StrictModel):
    author: Literal["customer", "agent"]
    body: str


class WrittenTicket(StrictModel):
    ticket_id: str
    subject: str
    messages: list[WrittenMessage]


class TicketBatch(StrictModel):
    tickets: list[WrittenTicket]


@dataclass(frozen=True)
class ReviewSeed:
    review_id: str
    product_id: str
    product_name: str
    item_id: str
    options: Mapping[str, str]
    user_id: str
    first_name: str
    rating: int
    topic: str
    days_before_anchor: float


@dataclass(frozen=True)
class TicketSeed:
    ticket_id: str
    intent: str
    user_id: str
    first_name: str
    order_id: str | None
    product_id: str | None
    situation: str
    outcome: Literal["resolved", "escalated"]
    csat: int | None
    turns: int
    days_before_anchor: float
    resolution_minutes: float


@dataclass(frozen=True)
class Written[T]:
    records: list[T]
    spent_usd: float
    stopped_at_cap: bool


def draft_reviews(store: RetailSnapshot, world: WorldConfig, *, count: int, seed: int) -> list[ReviewSeed]:
    draw = rng(seed, "reviews")
    bought = [(order, item) for order in store.orders.values() if order.status == "delivered" for item in order.items]
    speaker, variant = _speaker_variant(store)
    seeds: list[ReviewSeed] = []
    for index in range(8):
        owner = store.users[draw.choice(bought)[0].user_id]
        seeds.append(
            ReviewSeed(
                review_id=f"rv_{len(seeds):04d}",
                product_id=speaker.product_id,
                product_name=speaker.name,
                item_id=variant.item_id,
                options=dict(variant.options),
                user_id=owner.user_id,
                first_name=owner.name.first_name,
                rating=draw.choice((1, 1, 2)),
                topic="stops holding a charge after a few days",
                days_before_anchor=round(draw.uniform(3, 20) + index * 0.1, 2),
            )
        )
    while len(seeds) < count:
        order, item = draw.choice(bought)
        product = store.products[item.product_id]
        user = store.users[order.user_id]
        seeds.append(
            ReviewSeed(
                review_id=f"rv_{len(seeds):04d}",
                product_id=product.product_id,
                product_name=product.name,
                item_id=item.item_id,
                options=dict(item.options),
                user_id=user.user_id,
                first_name=user.name.first_name,
                rating=draw.choices(RATINGS, weights=RATING_WEIGHTS)[0],
                topic=draw.choice(REVIEW_TOPICS[world.category_of(product.name)]),
                days_before_anchor=round(draw.uniform(1, HISTORY_DAYS), 2),
            )
        )
    return seeds


def draft_tickets(
    store: RetailSnapshot, world: WorldConfig, shipments: Sequence[Shipment], *, count: int, seed: int
) -> list[TicketSeed]:
    draw = rng(seed, "tickets")
    seeds: list[TicketSeed] = []

    def add(intent: str, order: Order | None, product: Product | None, situation: str, *, days: float) -> None:
        user_id = order.user_id if order else draw.choice(list(store.users))
        escalated = draw.random() < 0.12
        seeds.append(
            TicketSeed(
                ticket_id=f"tk_h_{len(seeds):04d}",
                intent=intent,
                user_id=user_id,
                first_name=store.users[user_id].name.first_name,
                order_id=order.order_id if order else None,
                product_id=product.product_id if product else None,
                situation=situation,
                outcome="escalated" if escalated else "resolved",
                csat=None if escalated else draw.choices(RATINGS, weights=(0.5, 0.3, 0.1, 0.05, 0.05))[0],
                turns=draw.choice((2, 4, 4, 6)),
                days_before_anchor=round(days, 2),
                resolution_minutes=round(draw.uniform(4, 90), 1),
            )
        )

    speaker, variant = _speaker_variant(store)
    delivered = [o for o in store.orders.values() if o.status == "delivered"]
    for _ in range(10):
        order = draw.choice(delivered)
        add(
            "damaged_item",
            order,
            speaker,
            f"The customer's {speaker.name} ({_options(variant.options)}) stopped holding a charge after a few days; "
            "the agent offers a return or an exchange.",
            days=draw.uniform(4, 24),
        )
    late_midwest = [
        s
        for s in shipments
        if s.carrier == "northstar" and s.region == "midwest" and s.status in {"delivered", "in_transit"}
    ]
    for shipment in draw.sample(late_midwest, k=min(10, len(late_midwest))):
        add(
            "where_is_my_order",
            store.orders[shipment.order_id],
            None,
            f"The customer's Northstar Post parcel for order {shipment.order_id} to the Midwest is days late; "
            "the agent apologizes and gives a new estimate.",
            days=draw.uniform(2, 18),
        )
    intents = list(TICKET_MIX)
    while len(seeds) < count:
        intent = draw.choices(intents, weights=[TICKET_MIX[i] for i in intents])[0]
        order = _order_for(intent, store, draw.choice)
        product = store.products[order.items[0].product_id] if order else draw.choice(list(store.products.values()))
        situation = TICKET_SITUATIONS[intent].format(order=order.order_id if order else "", product=product.name)
        add(intent, order, product, situation, days=draw.uniform(1, HISTORY_DAYS))
    return seeds


async def write_reviews(
    models: ChatModels, seeds: Sequence[ReviewSeed], *, batch: int = 10, max_usd: float
) -> Written[ReviewRecord]:
    records: list[ReviewRecord] = []
    spent = 0.0
    for start in range(0, len(seeds), batch):
        chunk = seeds[start : start + batch]
        prompt = "Write these product reviews. Title: 2 to 8 words. Body: 1 to 4 sentences.\n\n" + "\n".join(
            f"- id {s.review_id}: {s.first_name} rates the {s.product_name} ({_options(s.options)}) "
            f"{s.rating} out of 5, mostly about {s.topic}."
            for s in chunk
        )
        written, cost = await _call(models, ReviewBatch, prompt)
        spent += cost
        by_id = {review.review_id: review for review in written.reviews}
        for s in chunk:
            review = by_id.get(s.review_id)
            if review is None:
                continue
            records.append(
                ReviewRecord(
                    review_id=s.review_id,
                    product_id=s.product_id,
                    item_id=s.item_id,
                    user_id=s.user_id,
                    rating=s.rating,
                    title=normalize(review.title),
                    body=normalize(review.body),
                    days_before_anchor=s.days_before_anchor,
                )
            )
        if spent >= max_usd and start + batch < len(seeds):
            return Written(records, spent, stopped_at_cap=True)
    return Written(records, spent, stopped_at_cap=False)


async def write_tickets(
    models: ChatModels, seeds: Sequence[TicketSeed], *, batch: int = 4, max_usd: float, seed: int
) -> Written[TicketRecord]:
    records: list[TicketRecord] = []
    spent = 0.0
    for start in range(0, len(seeds), batch):
        chunk = seeds[start : start + batch]
        prompt = (
            "Write these support conversations. Start with the customer and alternate. The subject is a short line the "
            "customer might type. Escalated conversations end with the agent handing over to a person.\n\n"
            + "\n".join(
                f"- id {s.ticket_id}: customer {s.first_name}. {s.situation} Outcome: {s.outcome}. "
                f"Exactly {s.turns} messages."
                for s in chunk
            )
        )
        written, cost = await _call(models, TicketBatch, prompt)
        spent += cost
        by_id = {ticket.ticket_id: ticket for ticket in written.tickets}
        for s in chunk:
            ticket = by_id.get(s.ticket_id)
            if ticket is None or not ticket.messages:
                continue
            records.append(_ticket_record(s, ticket, seed))
        if spent >= max_usd and start + batch < len(seeds):
            return Written(records, spent, stopped_at_cap=True)
    return Written(records, spent, stopped_at_cap=False)


_RANGE = re.compile("(\\d)(?:\\s*\u2013\\s*|\\s+-\\s+)(\\d)")
_DASHES = re.compile("\\s*[\u2014\u2013]\\s*|\\s+-\\s+")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def normalize(text: str) -> str:
    text = _RANGE.sub(r"\1 to \2", text.translate(_QUOTES))
    text = _DASHES.sub(", ", text)
    text = "".join(char for char in text if not _is_emoji(char))
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([,.!?;:])", r"\1", text).strip()


def _is_emoji(char: str) -> bool:
    return ord(char) >= 0x1F000 or char == "\ufe0f" or unicodedata.category(char) == "So"


async def _call[T: StrictModel](models: ChatModels, schema: type[T], prompt: str) -> tuple[T, float]:
    model = models.chat(WRITER).with_structured_output(schema, method="json_schema", include_raw=True)
    result = cast("dict[str, Any]", await model.ainvoke([SystemMessage(SYSTEM), HumanMessage(prompt)]))
    report = models.report(result["raw"])
    return schema.model_validate(result["parsed"]), report.cost_usd(models.price(WRITER))


def _ticket_record(seed_facts: TicketSeed, ticket: WrittenTicket, seed: int) -> TicketRecord:
    draw = rng(seed, "ticket-timing", seed_facts.ticket_id)
    minutes = 0.0
    messages: list[TicketMessageRecord] = []
    for message in ticket.messages:
        messages.append(
            TicketMessageRecord(author=message.author, body=normalize(message.body), minutes_after_open=minutes)
        )
        minutes = round(minutes + draw.uniform(1, 6), 1)
    return TicketRecord(
        ticket_id=seed_facts.ticket_id,
        user_id=seed_facts.user_id,
        order_id=seed_facts.order_id,
        product_id=seed_facts.product_id,
        intent=seed_facts.intent,
        subject=normalize(ticket.subject),
        status="escalated" if seed_facts.outcome == "escalated" else "resolved",
        csat=seed_facts.csat,
        days_before_anchor=seed_facts.days_before_anchor,
        resolution_minutes=max(seed_facts.resolution_minutes, minutes),
        messages=tuple(messages),
    )


def _speaker_variant(store: RetailSnapshot) -> tuple[Product, Variant]:
    speaker = next(p for p in store.products.values() if p.name == "Bluetooth Speaker")
    variant = min(speaker.variants.values(), key=lambda v: (v.options.get("battery life") != "20 hours", v.item_id))
    return speaker, variant


def _order_for(intent: str, store: RetailSnapshot, choose: Callable[[list[Order]], Order]) -> Order | None:
    statuses = {
        "where_is_my_order": {"delivered", "processed"},
        "return_items": {"delivered"},
        "exchange_items": {"delivered"},
        "damaged_item": {"delivered"},
        "cancel_order": {"cancelled"},
        "refund_status": {"cancelled"},
    }.get(intent)
    if statuses is None:
        return None
    return choose([order for order in store.orders.values() if order.status in statuses])


def _options(options: Mapping[str, str]) -> str:
    return ", ".join(f"{name} {value}" for name, value in options.items())

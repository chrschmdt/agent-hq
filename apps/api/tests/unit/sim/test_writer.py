from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from ahq.config import load_world_config
from ahq.domain.retail import RetailSnapshot
from ahq.sim.generate import generate_history
from ahq.sim.generate.writer import (
    draft_reviews,
    draft_tickets,
    normalize,
    write_reviews,
    write_tickets,
)
from ahq.testing import FakeChatModels

EM, EN = chr(0x2014), chr(0x2013)
LS, RS, LQ, RQ = chr(0x2018), chr(0x2019), chr(0x201C), chr(0x201D)
SMILE, FIRE, VS16 = chr(0x1F600), chr(0x1F525), chr(0xFE0F)


def ids_in(messages: Sequence[BaseMessage]) -> list[str]:
    return re.findall(r"id (\S+):", str(messages[-1].content))


def reviews_reply(messages: Sequence[BaseMessage]) -> str:
    written = [
        {"review_id": i, "title": f"Solid {EM} mostly", "body": f"Works well {SMILE} for {LQ}me{RQ}{EN}yes."}
        for i in ids_in(messages)
    ]
    return json.dumps({"reviews": written[:-1]})


def tickets_reply(messages: Sequence[BaseMessage]) -> str:
    return json.dumps(
        {
            "tickets": [
                {
                    "ticket_id": i,
                    "subject": "Late parcel",
                    "messages": [
                        {"author": "customer", "body": "Where is my order?"},
                        {"author": "agent", "body": "It arrives tomorrow."},
                    ],
                }
                for i in ids_in(messages)
            ]
        }
    )


def test_drafted_reviews_are_deterministic_and_come_from_real_buyers(tau3_snapshot: RetailSnapshot) -> None:
    world = load_world_config()
    seeds = draft_reviews(tau3_snapshot, world, count=60, seed=7)
    assert seeds == draft_reviews(tau3_snapshot, world, count=60, seed=7)
    assert len(seeds) == 60
    assert len({s.review_id for s in seeds}) == 60
    planted = seeds[:8]
    assert {s.product_name for s in planted} == {"Bluetooth Speaker"}
    assert len({s.item_id for s in planted}) == 1
    assert all(s.rating <= 2 for s in planted)
    for s in seeds[8:]:
        bought = {
            item.item_id
            for order in tau3_snapshot.orders.values()
            if order.user_id == s.user_id and order.status == "delivered"
            for item in order.items
        }
        assert s.item_id in bought


def test_drafted_tickets_include_both_planted_problems(tau3_snapshot: RetailSnapshot) -> None:
    world = load_world_config()
    history = generate_history(tau3_snapshot, world, seed=7)
    seeds = draft_tickets(tau3_snapshot, world, history.shipments, count=80, seed=7)
    assert len(seeds) == 80
    assert len({s.ticket_id for s in seeds}) == 80
    assert sum("stopped holding a charge" in s.situation for s in seeds) == 10
    assert sum("Northstar Post parcel" in s.situation for s in seeds) >= 5
    for s in seeds:
        assert (s.outcome == "escalated") == (s.csat is None)


def test_generated_text_follows_house_style() -> None:
    text = f"Great  kettle {EM} boils fast {FIRE}{VS16}, {LS}quiet{RS} {EN} 10{EN}12 min"
    assert normalize(text) == "Great kettle, boils fast, 'quiet', 10 to 12 min"
    assert normalize("One more thing - is it wi-fi only? It takes 3 - 5 days") == (
        "One more thing, is it wi-fi only? It takes 3 to 5 days"
    )


async def test_reviews_are_written_in_batches_and_missing_ones_are_skipped(tau3_snapshot: RetailSnapshot) -> None:
    models = FakeChatModels()
    models.script("writer", reviews_reply)
    seeds = draft_reviews(tau3_snapshot, load_world_config(), count=20, seed=7)
    written = await write_reviews(models, seeds, batch=10, max_usd=1.0)
    records = written.records
    assert (written.spent_usd, written.stopped_at_cap) == (0, False)
    assert len(records) == 18
    assert records[0].title == "Solid, mostly"
    assert records[0].body == 'Works well for "me", yes.'
    assert records[0].rating == seeds[0].rating


async def test_tickets_get_timed_messages(tau3_snapshot: RetailSnapshot) -> None:
    world = load_world_config()
    models = FakeChatModels()
    models.script("writer", tickets_reply)
    seeds = draft_tickets(tau3_snapshot, world, generate_history(tau3_snapshot, world, 7).shipments, count=8, seed=7)
    records = (await write_tickets(models, seeds, batch=4, max_usd=1.0, seed=7)).records
    assert [r.ticket_id for r in records] == [s.ticket_id for s in seeds]
    first = records[0].messages
    assert (first[0].minutes_after_open, first[1].minutes_after_open > 0) == (0.0, True)


async def test_writing_stops_at_the_spend_cap_and_keeps_what_it_has(tau3_snapshot: RetailSnapshot) -> None:
    models = FakeChatModels()
    models.script("writer", reviews_reply)
    seeds = draft_reviews(tau3_snapshot, load_world_config(), count=30, seed=7)
    written = await write_reviews(models, seeds, batch=10, max_usd=0.0)
    assert written.stopped_at_cap
    assert len(written.records) == 9

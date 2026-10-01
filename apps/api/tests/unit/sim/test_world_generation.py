from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from ahq.adapters.embedding_cache import CachingEmbedder
from ahq.adapters.memory import MemoryWorldRepo
from ahq.config import WorldConfig, load_world_config
from ahq.domain.retail import RetailSnapshot
from ahq.domain.world import WorldHistory
from ahq.ports import EmbeddingKind
from ahq.retail import InMemoryRetailRepo
from ahq.sim.generate import (
    ReviewRecord,
    TicketRecord,
    choose_carrier,
    fill_embeddings,
    generate_history,
    load_reviews,
    load_tickets,
    planned_transit,
)
from ahq.sim.seed import seed_world
from ahq.testing import HashEmbedder


@pytest.fixture(scope="module")
def world() -> WorldConfig:
    return load_world_config()


@pytest.fixture(scope="module")
def history(tau3_snapshot: RetailSnapshot, world: WorldConfig) -> WorldHistory:
    return generate_history(tau3_snapshot, world, seed=7)


def test_the_same_seed_gives_the_same_history(
    tau3_snapshot: RetailSnapshot, world: WorldConfig, history: WorldHistory
) -> None:
    assert generate_history(tau3_snapshot, world, seed=7) == history
    assert generate_history(tau3_snapshot, world, seed=8) != history


def test_every_order_gets_a_timeline_that_fits_its_status(
    tau3_snapshot: RetailSnapshot, world: WorldConfig, history: WorldHistory
) -> None:
    anchor = world.anchor
    shipments = {shipment.tracking_id: shipment for shipment in history.shipments}
    assert set(history.placed_at) == set(tau3_snapshot.orders)
    for order in tau3_snapshot.orders.values():
        placed = history.placed_at[order.order_id]
        parcels = [shipments[t] for f in order.fulfillments for t in f.tracking_id]
        assert placed < anchor
        if order.status == "pending":
            assert parcels == []
            assert anchor - placed <= timedelta(hours=36)
        elif order.status == "processed":
            for parcel in parcels:
                assert parcel.status == "in_transit"
                assert parcel.shipped_at is not None
                assert placed < parcel.shipped_at < anchor
                transit = planned_transit(choose_carrier(world, 7, parcel.tracking_id), 7, parcel.tracking_id)
                assert parcel.shipped_at + transit > anchor
        elif order.status == "delivered":
            for parcel in parcels:
                assert parcel.shipped_at is not None
                assert parcel.delivered_at is not None
                assert placed < parcel.shipped_at < parcel.delivered_at < anchor
        else:
            assert {parcel.status for parcel in parcels} == {"cancelled"}


def test_refunds_mirror_the_refunds_on_cancelled_orders(tau3_snapshot: RetailSnapshot, history: WorldHistory) -> None:
    expected = Counter(
        (order.order_id, payment.amount, payment.payment_method_id)
        for order in tau3_snapshot.orders.values()
        for payment in order.payment_history
        if payment.transaction_type == "refund"
    )
    assert Counter((r.order_id, r.amount, r.payment_method_id) for r in history.refunds) == expected


def test_carriers_share_the_parcels_roughly_as_configured(world: WorldConfig, history: WorldHistory) -> None:
    counts = Counter(shipment.carrier for shipment in history.shipments)
    for carrier in world.carriers:
        assert counts[carrier.id] / len(history.shipments) == pytest.approx(carrier.share, abs=0.06)


def test_kpis_cover_every_day_of_history_up_to_the_day_before_the_anchor(
    world: WorldConfig, history: WorldHistory
) -> None:
    days = sorted({point.day for point in history.kpis})
    assert len(days) == world.clock.history_days
    assert days[-1] == world.anchor.date() - timedelta(days=1)
    keys = Counter((point.day, point.metric, point.dimension, point.key) for point in history.kpis)
    assert max(keys.values()) == 1
    late = [p.value for p in history.kpis if p.metric == "late_delivery_rate" and p.dimension == "carrier"]
    assert all(0 <= value <= 0.9 for value in late)


def test_content_is_dated_relative_to_the_anchor(tmp_path: Path, world: WorldConfig) -> None:
    review = ReviewRecord(
        review_id="rv_1",
        product_id="p",
        item_id="i",
        user_id="u",
        rating=5,
        title="Great",
        body="Works well.",
        days_before_anchor=2.5,
    )
    ticket = TicketRecord.model_validate(
        {
            "ticket_id": "tk_1",
            "user_id": "u",
            "intent": "where_is_my_order",
            "subject": "Late parcel",
            "status": "resolved",
            "csat": 4,
            "days_before_anchor": 1,
            "resolution_minutes": 30,
            "messages": [
                {"author": "customer", "body": "Where is it?", "minutes_after_open": 0},
                {"author": "agent", "body": "Arriving tomorrow.", "minutes_after_open": 3},
            ],
        }
    )
    (tmp_path / "reviews.jsonl").write_text(review.model_dump_json() + "\n")
    (tmp_path / "tickets.jsonl").write_text(ticket.model_dump_json() + "\n")
    [loaded_review] = load_reviews(tmp_path / "reviews.jsonl", world.anchor)
    [loaded_ticket] = load_tickets(tmp_path / "tickets.jsonl", world.anchor)
    assert loaded_review.created_at == world.anchor - timedelta(days=2, hours=12)
    assert loaded_ticket.resolved_at == world.anchor - timedelta(days=1) + timedelta(minutes=30)
    assert [m.created_at - loaded_ticket.created_at for m in loaded_ticket.messages] == [
        timedelta(0),
        timedelta(minutes=3),
    ]
    assert load_reviews(tmp_path / "missing.jsonl", world.anchor) == ()


async def test_seeding_reports_what_it_wrote(tmp_path: Path, tau3_snapshot: RetailSnapshot, world: WorldConfig) -> None:
    report = await seed_world(
        InMemoryRetailRepo(tau3_snapshot), MemoryWorldRepo(), tau3_snapshot, world, seed=7, content_dir=tmp_path
    )
    assert (report.customers, report.products, report.variants, report.orders) == (500, 50, 591, 1000)
    assert (report.shipments, report.refunds, report.reviews, report.tickets) == (577, 102, 0, 0)


async def test_embeddings_fill_once(history: WorldHistory, tmp_path: Path) -> None:
    ticket = TicketRecord.model_validate(
        {
            "ticket_id": "tk_1",
            "user_id": "u",
            "intent": "other",
            "subject": "Hi",
            "status": "open",
            "days_before_anchor": 1,
            "messages": [{"author": "customer", "body": "Hello", "minutes_after_open": 0}],
        }
    ).to_ticket(load_world_config().anchor)
    repo = MemoryWorldRepo()
    await repo.load(history.model_copy(update={"tickets": (ticket,)}))
    assert await fill_embeddings(repo, HashEmbedder()) == {"reviews": 0, "ticket_messages": 1}
    assert await fill_embeddings(repo, HashEmbedder()) == {"reviews": 0, "ticket_messages": 0}


class CountingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.embedded: list[str] = []

    async def embed(self, texts: Sequence[str], kind: EmbeddingKind) -> list[list[float]]:
        self.embedded.extend(texts)
        return await super().embed(texts, kind)


async def test_the_embedding_cache_pays_for_each_text_once(tmp_path: Path) -> None:
    inner = CountingEmbedder()
    cache = CachingEmbedder(inner, tmp_path / "cache.sqlite", model="m")
    first = await cache.embed(["a", "b"], "document")
    second = await cache.embed(["b", "c", "a"], "document")
    cache.close()
    assert inner.embedded == ["a", "b", "c"]
    assert second == [first[1], *(await HashEmbedder().embed(["c"], "document")), first[0]]
    reopened = CachingEmbedder(CountingEmbedder(), tmp_path / "cache.sqlite", model="m")
    await reopened.embed(["a"], "document")
    await reopened.embed(["a"], "query")
    reopened.close()
    assert (reopened.hits, reopened.misses) == (1, 1)

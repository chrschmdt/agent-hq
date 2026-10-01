from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest

from ahq.adapters.memory import MemoryWorldRepo
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgRetailRepo, PgWorldRepo
from ahq.domain.world import KpiPoint, Refund, Review, Shipment, Ticket, TicketMessage, WorldHistory
from ahq.ports import WorldRepo
from tests.unit.retail.sample import CARD, sample_store

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def parcel(status: str = "in_transit", **times: datetime) -> Shipment:
    return Shipment.model_validate(
        {
            "tracking_id": "trk_1",
            "order_id": "#processed",
            "carrier": "swiftline",
            "state": "TX",
            "region": "texas",
            "status": status,
            **times,
        }
    )


def ticket(ticket_id: str = "tk_1") -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        user_id="ada_1",
        order_id="#processed",
        product_id="p_lamp",
        intent="where_is_my_order",
        subject="Where is my lamp?",
        status="open",
        source="simulation",
        created_at=NOW,
        messages=(
            TicketMessage(author="customer", body="My lamp has not arrived.", created_at=NOW),
            TicketMessage(author="agent", body="Let me check the tracking.", created_at=NOW + timedelta(minutes=2)),
        ),
    )


def sample_history() -> WorldHistory:
    return WorldHistory(
        placed_at={"#processed": NOW - timedelta(days=2)},
        shipments=(parcel(shipped_at=NOW - timedelta(days=1)),),
        refunds=(
            Refund(
                refund_id="rf_1",
                order_id="#pending",
                amount=50.0,
                payment_method_id=CARD,
                reason="order cancelled",
                created_at=NOW,
            ),
        ),
        reviews=(
            Review(
                review_id="rv_1",
                product_id="p_mug",
                item_id="mug_small",
                user_id="ada_1",
                rating=4,
                title="Solid mug",
                body="Keeps coffee warm.",
                created_at=NOW,
            ),
        ),
        tickets=(ticket("tk_history"),),
        kpis=(KpiPoint(day=date(2026, 6, 14), metric="orders", dimension="store", key="all", value=17, samples=17),),
    )


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
async def world(request: pytest.FixtureRequest) -> AsyncIterator[WorldRepo]:
    if request.param == "memory":
        repo = MemoryWorldRepo()
        await repo.load(sample_history())
        yield repo
        return
    engine = make_engine(request.getfixturevalue("pg_url"))
    sessions = make_sessionmaker(engine)
    await PgRetailRepo(sessions).load(sample_store())
    repo = PgWorldRepo(sessions)
    await repo.load(sample_history())
    yield repo
    await engine.dispose()


async def test_shipments_are_upserted_and_report_real_changes(world: WorldRepo) -> None:
    [shipment] = await world.shipments()
    assert await world.save_shipment(shipment) is False
    delivered = shipment.model_copy(update={"status": "delivered", "delivered_at": NOW})
    assert await world.save_shipment(delivered) is True
    assert await world.shipments() == [delivered]
    fresh = parcel("label_created").model_copy(update={"tracking_id": "trk_2"})
    assert await world.save_shipment(fresh) is True
    assert [s.tracking_id for s in await world.shipments()] == ["trk_1", "trk_2"]


async def test_tickets_open_once_and_read_back_with_their_messages(world: WorldRepo) -> None:
    assert await world.open_ticket(ticket()) is True
    assert await world.open_ticket(ticket()) is False
    assert await world.ticket("tk_1") == ticket()
    assert await world.ticket("tk_history") == ticket("tk_history")
    assert await world.ticket("tk_missing") is None


async def test_missing_embeddings_are_listed_until_saved(world: WorldRepo) -> None:
    assert await world.texts_to_embed("reviews", 10) == [("rv_1", "Solid mug\nKeeps coffee warm.")]
    await world.save_embeddings("reviews", {"rv_1": [0.1] * 1024})
    assert await world.texts_to_embed("reviews", 10) == []
    messages = await world.texts_to_embed("ticket_messages", 1)
    assert messages == [("tk_history:0", "My lamp has not arrived.")]
    await world.save_embeddings("ticket_messages", {"tk_history:0": [0.2] * 1024})
    assert await world.texts_to_embed("ticket_messages", 10) == [("tk_history:1", "Let me check the tracking.")]


async def test_kpis_come_back_for_the_last_days(world: WorldRepo) -> None:
    (point,) = await world.kpis("orders", "store", days=7)
    assert (point.day, point.key, point.value) == (date(2026, 6, 14), "all", 17)
    assert await world.kpis("csat", "store", days=7) == []

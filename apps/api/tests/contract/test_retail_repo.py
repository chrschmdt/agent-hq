from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgRetailRepo
from ahq.domain import DuplicateCall, ToolCallRecord
from ahq.domain.retail import Address, GiftCard, Payment, RetailChange, RetailSnapshot
from ahq.ports import RetailRepo
from ahq.retail import InMemoryRetailRepo, RetailService, canonical_hash, format_output
from tests.unit.retail.sample import GIFT, sample_store


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[RetailRepo]:
    if request.param == "memory":
        yield InMemoryRetailRepo(sample_store())
        return
    engine = make_engine(request.getfixturevalue("pg_url"))
    repo = PgRetailRepo(make_sessionmaker(engine))
    await repo.load(sample_store())
    yield repo
    await engine.dispose()


async def test_a_loaded_store_reads_back_exactly(repo: RetailRepo) -> None:
    snapshot = await repo.snapshot()
    assert snapshot == sample_store()
    assert canonical_hash(snapshot) == canonical_hash(sample_store())


async def test_lookups(repo: RetailRepo) -> None:
    async with repo.session() as session:
        ada = await session.user("ada_1")
        assert ada is not None
        assert list(ada.payment_methods) == ["credit_card_1", "gift_card_1"]
        assert ada.orders == ["#pending", "#pending_gift", "#modified", "#processed", "#delivered"]
        assert await session.user("nobody") is None
        assert await session.user_id_by_email("ADA@example.com") == "ada_1"
        assert await session.user_id_by_email("grace@example.com") is None
        assert await session.user_id_by_name_zip("ADA", "lovelace", "78701") == "ada_1"
        order = await session.order("#delivered")
        assert order is not None
        assert [item.item_id for item in order.items] == ["mug_small", "lamp_white"]
        product = await session.product("p_mug")
        assert product is not None
        assert list(product.variants) == ["mug_small", "mug_large", "mug_gold"]
        variant = await session.variant("lamp_black")
        assert variant is not None
        assert variant.price == 55.0
        assert [p.name for p in await session.products()] == ["Mug", "Lamp"]


async def test_saved_changes_are_visible_to_later_sessions(repo: RetailRepo) -> None:
    async with repo.session() as session:
        ada = await session.user("ada_1")
        order = await session.order("#pending")
        assert ada is not None
        assert order is not None
        moved = ada.model_copy(
            update={
                "address": Address(address1="9 Elm", address2="", city="Reno", country="USA", state="NV", zip="89501"),
                "payment_methods": {
                    **ada.payment_methods,
                    GIFT: GiftCard(source="gift_card", id=GIFT, balance=12.34),
                },
            }
        )
        updated = order.model_copy(
            update={
                "status": "cancelled",
                "cancel_reason": "ordered by mistake",
                "items": order.items[:1],
                "payment_history": [
                    *order.payment_history,
                    Payment(transaction_type="refund", amount=50.0, payment_method_id="credit_card_1"),
                ],
                "return_items": ["mug_small"],
            }
        )
        await session.save(RetailChange(users=(moved,), orders=(updated,)))
    snapshot = await repo.snapshot()
    assert snapshot.users["ada_1"] == moved
    assert snapshot.orders["#pending"] == updated


async def _save_then_fail(repo: RetailRepo) -> None:
    async with repo.session() as session:
        order = await session.order("#pending")
        assert order is not None
        await session.save(RetailChange(orders=(order.model_copy(update={"status": "cancelled"}),)))
        raise RuntimeError("the tool failed after saving")


async def test_a_failed_session_writes_nothing(repo: RetailRepo) -> None:
    before = await repo.snapshot()
    with pytest.raises(RuntimeError):
        await _save_then_fail(repo)
    assert await repo.snapshot() == before


async def test_load_replaces_the_whole_store(repo: RetailRepo, tau3_snapshot: RetailSnapshot) -> None:
    await repo.load(tau3_snapshot)
    loaded = await repo.snapshot()
    assert (len(loaded.users), len(loaded.products), len(loaded.orders)) == (500, 50, 1000)
    assert canonical_hash(loaded) == canonical_hash(tau3_snapshot)


async def change_email(repo: RetailRepo, record: ToolCallRecord) -> None:
    async with repo.session() as session:
        ada = await session.user("ada_1")
        assert ada is not None
        await session.save(RetailChange(users=(ada.model_copy(update={"email": "new@example.com"}),), call=record))


async def test_a_write_records_its_call_and_refuses_a_second_one(repo: RetailRepo) -> None:
    record = ToolCallRecord(
        key=f"th_contract:call_{secrets.token_hex(4)}",
        work_item_id=None,
        subject="support",
        tool="cancel_pending_order",
        arguments={"order_id": "#pending", "reason": "no longer needed"},
        output="",
        recorded_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
    )
    order = await RetailService(repo).recording(record).cancel_pending_order("#pending", "no longer needed")
    stored = await repo.recorded_call(record.key)
    assert stored is not None
    assert stored.output == format_output(order)
    assert await repo.recorded_call("th_contract:never") is None

    with pytest.raises(DuplicateCall):
        await change_email(repo, record)
    async with repo.session() as session:
        ada = await session.user("ada_1")
        assert ada is not None
        assert ada.email == "Ada@Example.com"

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest

from ahq.analytics import cluster_tickets, get_kpis, run_readonly_sql, similar_tickets
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgReadOnlySql, PgRetailRepo, PgWorldRepo
from ahq.domain.world import Ticket, TicketMessage
from ahq.ports import AnalyticsError
from ahq.testing import HashEmbedder
from tests.unit.retail.sample import sample_store

pytestmark = pytest.mark.db

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
OPENINGS = {
    "tk_late_1": ("delivery", "My parcel from Northstar Post is late and still not in Ohio"),
    "tk_late_2": ("delivery", "Northstar Post parcel late again, Ohio delivery missed"),
    "tk_late_3": ("delivery", "late Northstar Post parcel to Ohio, where is it"),
    "tk_speaker_1": ("product", "speaker battery stopped holding a charge"),
    "tk_speaker_2": ("product", "the speaker battery will not hold a charge anymore"),
    "tk_speaker_3": ("product", "battery on my speaker does not hold charge"),
}


@pytest.fixture
async def db(pg_url: str) -> AsyncIterator[PgReadOnlySql]:
    engine = make_engine(pg_url)
    sessions = make_sessionmaker(engine)
    await PgRetailRepo(sessions).load(sample_store())
    world, embedder = PgWorldRepo(sessions), HashEmbedder()
    for index, (ticket_id, (intent, text)) in enumerate(OPENINGS.items()):
        opened = NOW - timedelta(days=index)
        message = TicketMessage(author="customer", body=text, created_at=opened)
        ticket = Ticket(
            ticket_id=ticket_id,
            user_id=None,
            intent=intent,
            subject=text[:40],
            status="resolved",
            source="history",
            created_at=opened,
            messages=(message,),
        )
        await world.open_ticket(ticket)
    vectors = await embedder.embed([text for _, text in OPENINGS.values()], "document")
    await world.save_embeddings("ticket_messages", {f"{key}:0": v for key, v in zip(OPENINGS, vectors, strict=True)})
    with psycopg.connect(pg_url, autocommit=True) as connection:
        connection.execute("DELETE FROM kpi.daily")
        for offset in range(5):
            connection.execute(
                "INSERT INTO kpi.daily (day, metric, dimension, key, value, samples) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    date(2026, 6, 10) + timedelta(days=offset),
                    "late_delivery_rate",
                    "carrier",
                    "northstar",
                    round(0.1 * offset, 2),
                    20,
                ),
            )
    yield PgReadOnlySql(sessions, timeout_ms=1000)
    await engine.dispose()


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("DELETE FROM retail.orders", "read-only transaction"),
        ("UPDATE retail.orders SET status = 'x'", "read-only transaction"),
        ("SELECT * FROM ops.work_items", "permission denied"),
        ("SELECT * FROM agents.tool_calls_audit", "permission denied"),
        ("SELECT count(*) FROM generate_series(1, 1000000000)", "longer than 1 seconds"),
    ],
)
async def test_the_role_refuses_what_the_guard_would_have_caught(db: PgReadOnlySql, sql: str, message: str) -> None:
    with pytest.raises(AnalyticsError, match=message):
        await db.fetch(sql)


async def test_an_analyst_query_runs_with_its_percent_signs_and_colons(db: PgReadOnlySql) -> None:
    result = await run_readonly_sql(
        db, "select ticket_id, 'a:b' as label from support.tickets where subject like '%Northstar%' order by 1"
    )
    assert result.columns == ["ticket_id", "label"]
    assert [row[0] for row in result.rows] == ["tk_late_1", "tk_late_2", "tk_late_3"]


async def test_kpis_come_back_by_day(db: PgReadOnlySql) -> None:
    rows = await get_kpis(db, "late_delivery_rate", "carrier", date(2026, 6, 11), date(2026, 6, 13), key="northstar")
    assert [(row.day.day, row.value) for row in rows] == [(11, 0.1), (12, 0.2), (13, 0.3)]


async def test_similar_tickets_are_found_by_meaning_and_filtered_in_the_same_statement(db: PgReadOnlySql) -> None:
    embedder, since = HashEmbedder(), NOW - timedelta(days=30)
    found = await similar_tickets(db, embedder, "Northstar Post parcel late in Ohio", since, NOW + timedelta(days=1))
    assert {t.ticket_id for t in found[:3]} == {"tk_late_1", "tk_late_2", "tk_late_3"}
    assert found[0].similarity > found[-1].similarity
    only_products = await similar_tickets(
        db, embedder, "Northstar Post parcel late", since, NOW + timedelta(days=1), intent="product"
    )
    assert {t.intent for t in only_products} == {"product"}


async def test_tickets_cluster_by_theme(db: PgReadOnlySql) -> None:
    clusters = await cluster_tickets(db, NOW - timedelta(days=30), NOW + timedelta(days=1), k_max=4)
    themes = sorted(sorted(cluster.ticket_ids) for cluster in clusters)
    assert themes == [["tk_late_1", "tk_late_2", "tk_late_3"], ["tk_speaker_1", "tk_speaker_2", "tk_speaker_3"]]

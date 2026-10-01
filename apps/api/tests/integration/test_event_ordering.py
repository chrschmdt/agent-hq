from __future__ import annotations

import psycopg
import pytest

from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgEventLog

pytestmark = pytest.mark.db

INSERT = "INSERT INTO ops.events (kind, occurred_at) VALUES ('work.created', now()) RETURNING id"


async def test_readers_wait_for_an_older_open_transaction(clean_db: str) -> None:
    engine = make_engine(clean_db)
    log = PgEventLog(make_sessionmaker(engine))
    try:
        async with (
            await psycopg.AsyncConnection.connect(clean_db) as slow,
            await psycopg.AsyncConnection.connect(clean_db, autocommit=True) as fast,
        ):
            slow_id = (await (await slow.execute(INSERT)).fetchone() or [0])[0]
            fast_id = (await (await fast.execute(INSERT)).fetchone() or [0])[0]
            assert fast_id > slow_id

            assert await log.read_after(0) == []

            await slow.commit()
            assert [event.id for event in await log.read_after(0)] == [slow_id, fast_id]
    finally:
        await engine.dispose()

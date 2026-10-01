from __future__ import annotations

import psycopg
import pytest

from ahq.adapters.clock import ManualClock
from ahq.db.activity import ACTIVITY_TABLES, activity_counts, clear_activity
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgWorkStore
from ahq.domain import WorkKind

pytestmark = pytest.mark.db


async def test_activity_is_cleared_and_the_store_and_versions_stay(pg_url: str) -> None:
    engine = make_engine(pg_url)
    try:
        await PgWorkStore(make_sessionmaker(engine), ManualClock()).create(WorkKind.SMOKE, {})
        with psycopg.connect(pg_url, autocommit=True) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS retail.clear_probe (id int)")
            connection.execute("INSERT INTO retail.clear_probe VALUES (1)")
            versions_before = connection.execute("SELECT count(*) FROM agents.agent_versions").fetchone()
        before = await activity_counts(engine, versions=False)
        assert before["ops.work_items"] >= 1
        assert set(ACTIVITY_TABLES) <= set(before)
        assert "agents.agent_versions" not in before
        assert not {"ops.recordings", "ops.settings"} & set(before)

        cleared = await clear_activity(engine, versions=False)
        assert cleared == before
        assert set((await activity_counts(engine, versions=False)).values()) == {0}
        with psycopg.connect(pg_url, autocommit=True) as connection:
            assert connection.execute("SELECT count(*) FROM retail.clear_probe").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM agents.agent_versions").fetchone() == versions_before
            connection.execute("DROP TABLE retail.clear_probe")
    finally:
        await engine.dispose()

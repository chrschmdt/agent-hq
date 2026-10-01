from __future__ import annotations

import json
from typing import Any

import pytest

from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgRetailRepo
from ahq.domain.retail import RetailChange, RetailSnapshot
from ahq.retail import InMemoryRetailRepo, RetailService, canonical_hash, run_action
from tests.conftest import TAU3_DIR

pytestmark = pytest.mark.db


def _parsed(output: str) -> Any:
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output


async def test_every_reference_replay_matches_in_postgres(pg_url: str, tau3_snapshot: RetailSnapshot) -> None:
    tasks = json.loads((TAU3_DIR / "tasks.json").read_text())
    engine = make_engine(pg_url)
    sql = PgRetailRepo(make_sessionmaker(engine))
    try:
        await sql.load(tau3_snapshot)
        for task in tasks:
            memory = InMemoryRetailRepo(tau3_snapshot)
            actions = task["evaluation_criteria"]["actions"] or []
            for action in actions:
                expected = await run_action(RetailService(memory), action["name"], action["arguments"])
                actual = await run_action(RetailService(sql), action["name"], action["arguments"])
                assert (_parsed(actual.output), actual.error) == (_parsed(expected.output), expected.error), task["id"]
            after = await memory.snapshot()
            users = [u for key, u in after.users.items() if u != tau3_snapshot.users[key]]
            orders = [o for key, o in after.orders.items() if o != tau3_snapshot.orders[key]]
            async with sql.session() as session:
                for user in users:
                    assert await session.user(user.user_id) == user, task["id"]
                for order in orders:
                    assert await session.order(order.order_id) == order, task["id"]
                await session.save(
                    RetailChange(
                        users=tuple(tau3_snapshot.users[u.user_id] for u in users),
                        orders=tuple(tau3_snapshot.orders[o.order_id] for o in orders),
                    )
                )
        assert canonical_hash(await sql.snapshot()) == canonical_hash(tau3_snapshot)
    finally:
        await engine.dispose()

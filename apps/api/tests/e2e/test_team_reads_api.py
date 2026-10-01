from __future__ import annotations

from ahq.app.container import Overrides
from ahq.domain.retail import RetailSnapshot
from tests.e2e.conftest import OPERATOR, running
from tests.e2e.test_offline_team import RETURN


async def test_a_runs_thread_shows_each_step_with_the_rule_behind_it(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        opened = (await run.http.post("/api/tickets", json={"message": RETURN}, headers=OPERATOR)).json()
        await run.queue.run_until_idle()
        work_id = opened["work_item"]["id"]
        thread = (await run.http.get(f"/api/runs/{work_id}/thread")).json()
        messages = thread["channels"]["support"]
        assert messages[0]["kind"] == "customer"
        models = [m for m in messages if m["kind"] == "model"]
        assert all(m["reasoning"].startswith("Rule: ") for m in models)
        assert thread["route"]["route"] == "support"
        calls = [e for e in (await run.http.get(f"/api/runs/{work_id}")).json()["events"] if e["kind"] == "tool.called"]
        called = {c["id"] for m in models for c in m["tool_calls"]}
        assert {e["payload"]["call_id"] for e in calls} <= called
        assert all(e["recorded_at"] for e in calls)


async def test_the_lineup_names_the_model_behind_every_role() -> None:
    async with running() as run:
        lineup = (await run.http.get("/api/lineup")).json()
        assert lineup["profile"] == "mock"
        assert {"guard", "dispatcher", "support", "ops", "insights", "qa", "customer"} <= set(lineup["roles"])
        assert lineup["roles"]["support"] == {"key": "fake", "id": "fake", "provider": "fake", "reasoning": False}


async def test_recent_events_can_be_asked_for_by_kind(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        await run.http.post("/api/tickets", json={"message": RETURN}, headers=OPERATOR)
        await run.queue.run_until_idle()
        recent = (await run.http.get("/api/events/recent", params={"kind": ["work.created", "work.routed"]})).json()
        assert [e["kind"] for e in recent] == ["work.routed", "work.created"]

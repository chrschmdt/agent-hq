from __future__ import annotations

from ahq.app.container import Overrides
from ahq.domain.retail import RetailSnapshot
from tests.e2e.conftest import OPERATOR, running
from tests.e2e.test_recordings_api import DAY, played
from tests.e2e.test_simulator_api import seeded


async def test_the_admin_clears_the_activity_and_keeps_the_recorded_day(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        run_id = await played(run, tau3_snapshot)
        recorded = (await run.http.post("/api/recordings", json={"sim_run_id": run_id}, headers=OPERATOR)).json()
        config = (await run.http.get("/api/versions/dispatcher@1")).json()["config"]
        drafted = {"config": {**config, "max_usd": 0.03}, "note": "A little more room per decision."}
        assert (await run.http.post("/api/agents/dispatcher/versions", json=drafted, headers=OPERATOR)).is_success
        last = (await run.http.get("/api/status")).json()["last_event_id"]

        assert (await run.http.post("/api/activity/clear", json={})).status_code == 401
        report = (await run.http.post("/api/activity/clear", json={"versions": True}, headers=OPERATOR)).json()
        assert report["records"]["ops.events"] == last
        assert report["records"]["ops.work_items"] > 0
        assert report["records"]["agents.incidents"] == 1
        assert report["records"]["agents.agent_versions"] == 5
        assert report["passages"] > 0
        assert report["versions"]

        cleared, *seeded_again = (await run.http.get("/api/events", params={"after": 0})).json()
        assert (cleared["id"], cleared["kind"]) == (last + 1, "activity.cleared")
        assert {event["payload"]["version_id"] for event in seeded_again} == {
            "dispatcher@1",
            "support@1",
            "ops@1",
            "insights@1",
        }
        assert (await run.http.get("/api/work")).json() == []
        assert (await run.http.get("/api/incidents")).json() == []
        assert (await run.http.get("/api/sim/runs", headers=OPERATOR)).json() == []
        versions = (await run.http.get("/api/versions", params={"agent": "dispatcher"})).json()
        assert [(v["version_id"], v["status"]) for v in versions] == [("dispatcher@1", "live")]
        assert [r["id"] for r in (await run.http.get("/api/recordings")).json()] == [recorded["id"]]


async def test_nothing_is_cleared_while_a_day_runs(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        await seeded(run, tau3_snapshot)
        started = (await run.http.post("/api/sim/start", json=DAY, headers=OPERATOR)).json()
        refused = await run.http.post("/api/activity/clear", json={}, headers=OPERATOR)
        assert refused.status_code == 409
        await run.http.post(f"/api/sim/{started['run_id']}/stop", headers=OPERATOR)
        await run.queue.run_until_idle()
        assert (await run.http.post("/api/activity/clear", json={}, headers=OPERATOR)).is_success
        assert run.queue.dead_letters == []

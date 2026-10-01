from __future__ import annotations

from ahq.app.container import Overrides
from ahq.domain.retail import RetailSnapshot
from ahq.testing import FakeChatModels
from tests.e2e.conftest import OPERATOR, running
from tests.e2e.test_simulator_api import seeded
from tests.e2e.test_team_flow import proposing_the_draft
from tests.unit.graphs.harness import DRAFT, calls, incident, route

NORTHSTAR = {"carrier": "northstar", "region": "northeast", "category": None, "item_id": None, "order_ids": []}


async def test_the_screens_read_a_whole_day(tau3_snapshot: RetailSnapshot) -> None:
    models = FakeChatModels()
    models.script("dispatcher", route("ops"))
    models.script("ops", incident("insights", affected=NORTHSTAR))
    models.script("insights", calls(DRAFT), proposing_the_draft)
    async with running(Overrides(models=models, store=tau3_snapshot)) as run:
        await seeded(run, tau3_snapshot)
        body = {"scenario": "carrier-delay", "seed": 7, "tick_seconds": 1, "alerts_to_agents": True}
        await run.http.post("/api/sim/start", json=body, headers=OPERATOR)
        await run.queue.run_until_idle()

        (alert,) = (await run.http.get("/api/work", params={"kind": "alert"})).json()
        assert (alert["status"], alert["owner"]) == ("done", "insights")
        assert (await run.http.get("/api/work", params={"status": ["waiting_approval"]})).json() == []

        view = (await run.http.get(f"/api/runs/{alert['id']}")).json()
        assert [step["node"] for step in view["path"]] == ["dispatcher", "ops", "insights"]
        assert view["incident"]["report"]["affected"]["region"] == "northeast"
        assert len(view["proposals"]) == 1
        assert (view["traced"], view["ticket"]) == (False, None)

        graph = (await run.http.get("/api/graph")).json()
        assert {node["id"] for node in graph["team"]["nodes"]} >= {"dispatcher", "support", "ops", "insights"}
        assert {"source": "ops", "target": "insights", "conditional": True} in graph["team"]["edges"]

        agents = {agent["name"]: agent for agent in (await run.http.get("/api/agents")).json()}
        assert set(agents) == {"dispatcher", "support", "ops", "insights"}
        assert agents["insights"]["work"] == {"done": 1}
        ops = (await run.http.get("/api/agents/ops")).json()
        assert ops["prompt_context"].startswith("## Context")
        assert ops["models_by_profile"]["high"] == "claude-opus-5-5"
        assert {event["kind"] for event in ops["recent_events"]} >= {"agent.handoff"}
        assert (await run.http.get("/api/agents/nobody")).status_code == 404

        described = await run.http.get("/api/tools/return_delivered_order_items")
        assert "s-maxage" in described.headers["cache-control"]
        tool = described.json()
        assert tool["refund_gated"] is True
        assert "item_ids" in tool["parameters"]["properties"]

        orders = (await run.http.get("/api/kpis", params={"metric": "orders", "days": 7})).json()
        assert len(orders) == 7
        assert {point["key"] for point in orders} == {"all"}

        query = {"query": "When does a refund reach my card?", "k": 3}
        assert (await run.http.post("/api/retrieval/search", json=query)).status_code == 401
        found = (await run.http.post("/api/retrieval/search", json=query, headers=OPERATOR)).json()
        assert len(found["passages"]) == 3
        trace = found["trace"]
        assert trace["reranked"][0]["passage_id"] == found["passages"][0]["passage_id"]
        assert {p["passage_id"] for p in trace["candidates"]} >= {r["passage_id"] for r in trace["fused"]}

        similar = await run.http.post("/api/analytics/similar-tickets", json={"text": "late"}, headers=OPERATOR)
        assert similar.status_code == 503

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

from ahq.api.recordings import publish_file
from ahq.app.container import Overrides
from ahq.domain.retail import RetailSnapshot
from tests.e2e.conftest import OPERATOR, Running, running
from tests.e2e.test_simulator_api import seeded

DAY = {"scenario": "carrier-delay", "seed": 7, "agent_tickets": 2, "alerts_to_agents": True}


async def played(run: Running, store: RetailSnapshot) -> str:
    await seeded(run, store)
    started = (await run.http.post("/api/sim/start", json=DAY, headers=OPERATOR)).json()
    await run.queue.run_until_idle()
    return started["run_id"]


async def test_a_finished_day_is_recorded_published_and_replayed_as_it_happened(
    tau3_snapshot: RetailSnapshot, tmp_path: Path
) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        run_id = await played(run, tau3_snapshot)
        assert (await run.http.get("/api/sim/runs")).status_code == 401
        (day,) = (await run.http.get("/api/sim/runs", headers=OPERATOR)).json()
        assert (day["run_id"], day["status"]) == (run_id, "finished")

        assert (await run.http.post("/api/recordings", json={"sim_run_id": run_id})).status_code == 401
        info = (await run.http.post("/api/recordings", json={"sim_run_id": run_id}, headers=OPERATOR)).json()
        assert info["published"]
        assert info["title"].startswith("Carrier delay, ")
        assert (info["summary"]["scenario"], info["summary"]["profile"]) == ("carrier-delay", "mock")
        assert info["summary"]["agent_tickets"] == 2
        assert info["summary"]["incidents"] == 1

        assert [r["id"] for r in (await run.http.get("/api/recordings")).json()] == [info["id"]]
        response = await run.http.get(f"/api/recordings/{info['id']}")
        assert response.headers["content-encoding"] == "gzip"
        assert "s-maxage=3600" in response.headers["cache-control"]
        recording: dict[str, Any] = response.json()
        assert (recording["version"], recording["id"]) == (2, info["id"])
        assert recording["events"][0]["kind"] == "sim.started"
        assert recording["lineup"]["roles"]["support"]["key"] == "fake"
        assert {a["detail"]["name"] for a in recording["agents"]} == {"dispatcher", "support", "ops", "insights"}
        assert set(recording["kpis"]) == {"orders", "late_delivery_rate", "tickets", "csat"}

        store = recording["store"]
        opened = {e["payload"]["ticket_id"] for e in recording["events"] if e["kind"] == "ticket.opened"}
        assert {ticket["ticket_id"] for ticket in store["tickets"]} == opened
        orders = {order["order_id"] for order in store["orders"]}
        assert {ticket["order_id"] for ticket in store["tickets"] if ticket["order_id"]} <= orders
        assert {order["user_id"] for order in store["orders"]} <= {c["user_id"] for c in store["customers"]}
        assert store["shipments"]
        assert all(shipment["order_id"] in orders for shipment in store["shipments"])

        named = {e["work_item_id"] for e in recording["events"] if e["work_item_id"]}
        assert named == set(recording["runs"]) == {w["item"]["id"] for w in recording["work"]}
        for work in recording["work"]:
            assert work["changes"][0]["at"] >= work["at"]
            assert work["changes"][-1]["status"] == work["item"]["status"]
            ats = [change["at"] for change in work["changes"]]
            assert ats == sorted(ats)
        for recorded in recording["runs"].values():
            channels = (recorded["thread"] or {}).get("channels", {})
            assert {name: len(messages) for name, messages in channels.items()} == {
                name: len(times) for name, times in recorded["message_at"].items()
            }
            for times in recorded["message_at"].values():
                assert times == sorted(times)

        (incident,) = recording["incidents"]
        assert len(recording["proposals"]) == 2
        assert all(p["pending"]["status"] == "pending" and p["at"] >= incident["at"] for p in recording["proposals"])
        tickets = [point["value"]["tickets"] for point in recording["value"]]
        assert tickets == sorted(tickets)
        assert recording["value"][-1]["value"]["incidents"] == 1

        saved = tmp_path / "day.json.gz"
        saved.write_bytes(gzip.compress(response.content))
        withdrawn = await run.http.patch(f"/api/recordings/{info['id']}", json={"published": False}, headers=OPERATOR)
        assert not withdrawn.json()["published"]
        assert (await run.http.get("/api/recordings")).json() == []
        assert (await run.http.get(f"/api/recordings/{info['id']}")).status_code == 404
        assert (await run.http.get(f"/api/recordings/{info['id']}", headers=OPERATOR)).status_code == 200
        assert len((await run.http.get("/api/recordings", headers=OPERATOR)).json()) == 1
        deleted = await run.http.delete(f"/api/recordings/{info['id']}", headers=OPERATOR)
        assert deleted.status_code == 204
        assert (await run.http.get("/api/recordings", headers=OPERATOR)).json() == []

    async with running() as fresh:
        published = await publish_file(fresh.container, saved, by="offline")
        assert (published.id, published.summary.incidents) == (info["id"], 1)
        assert [r["id"] for r in (await fresh.http.get("/api/recordings")).json()] == [info["id"]]


async def test_a_day_still_running_cannot_be_recorded(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        await seeded(run, tau3_snapshot)
        started = (await run.http.post("/api/sim/start", json=DAY, headers=OPERATOR)).json()
        refused = await run.http.post("/api/recordings", json={"sim_run_id": started["run_id"]}, headers=OPERATOR)
        assert refused.status_code == 409
        missing = await run.http.post("/api/recordings", json={"sim_run_id": "sim_missing"}, headers=OPERATOR)
        assert missing.status_code == 404

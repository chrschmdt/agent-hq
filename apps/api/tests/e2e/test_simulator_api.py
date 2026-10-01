from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from langchain_core.messages import AIMessage

from ahq.app.container import Overrides
from ahq.config import load_world_config
from ahq.domain.retail import RetailSnapshot
from ahq.sim.seed import seed_world
from ahq.testing import FakeChatModels
from tests.conftest import TAU3_DIR
from tests.e2e.conftest import OPERATOR, Running, running


async def seeded(run: Running, store: RetailSnapshot) -> None:
    container = run.container
    await seed_world(
        container.retail, container.world, store, load_world_config(), seed=7, content_dir=TAU3_DIR / "none"
    )
    await container.baseline.capture()


async def test_a_day_played_through_the_api(tau3_snapshot: RetailSnapshot) -> None:
    async with running() as run:
        await seeded(run, tau3_snapshot)
        assert (await run.http.post("/api/sim/start", json={})).status_code == 401

        started = await run.http.post("/api/sim/start", json={"seed": 7, "tick_seconds": 1}, headers=OPERATOR)
        assert started.status_code == 201
        run_id = started.json()["run_id"]
        status = (await run.http.get("/api/status")).json()
        assert (status["simulating"], status["active"]) == (True, True)

        paused = await run.http.post(f"/api/sim/{run_id}/pause", headers=OPERATOR)
        assert paused.json()["status"] == "paused"
        assert (await run.http.post(f"/api/sim/{run_id}/pause", headers=OPERATOR)).status_code == 409
        await run.http.post(f"/api/sim/{run_id}/resume", headers=OPERATOR)
        await run.queue.run_until_idle()

        state = (await run.http.get("/api/sim")).json()
        assert (state["run"]["status"], state["run"]["tick_no"]) == ("finished", 288)
        names = [scenario["name"] for scenario in state["scenarios"]]
        assert names == [
            "normal-day",
            "carrier-delay",
            "bad-deploy",
            "surge",
            "prompt-injection",
            "refund-pressure",
            "defective-batch",
            "policy-change",
            "showcase",
        ]
        assert (await run.http.get("/api/status")).json()["simulating"] is False

        kinds: Counter[str] = Counter()
        cursor = 0
        while page := (await run.http.get("/api/events", params={"after": cursor, "limit": 500})).json():
            kinds.update(event["kind"] for event in page)
            cursor = page[-1]["id"]
        assert kinds["ticket.opened"] == 150
        assert (kinds["sim.started"], kinds["sim.paused"], kinds["sim.resumed"], kinds["sim.finished"]) == (1, 1, 1, 1)


async def test_unknown_scenarios_and_runs_are_not_found(tau3_snapshot: RetailSnapshot) -> None:
    async with running() as run:
        await seeded(run, tau3_snapshot)
        unknown = await run.http.post("/api/sim/start", json={"scenario": "alien-invasion"}, headers=OPERATOR)
        assert unknown.status_code == 404
        assert (await run.http.post("/api/sim/sim_missing/pause", headers=OPERATOR)).status_code == 404
        reset = await run.http.post("/api/sim/reset", headers=OPERATOR)
        assert reset.status_code == 204


async def test_the_first_tickets_of_a_day_go_to_the_agents(tau3_snapshot: RetailSnapshot) -> None:
    models = FakeChatModels()
    models.script(
        "support",
        AIMessage(
            content=json.dumps(
                {"reply": "Happy to help.", "citations": [], "status": "awaiting_customer", "summary": "Greeted"}
            )
        ),
    )
    models.script("customer", "That is all, thanks. ###STOP###", json.dumps({"score": 4, "reason": "Fine."}))
    async with running(Overrides(models=models)) as run:
        await seeded(run, tau3_snapshot)
        body = {"seed": 7, "tick_seconds": 1, "agent_tickets": 1}
        assert (await run.http.post("/api/sim/start", json=body, headers=OPERATOR)).status_code == 201
        await run.queue.run_until_idle()

        handed = await run.container.tickets.ticket("tk_7_0000")
        untouched = await run.container.tickets.ticket("tk_7_0001")
        assert handed is not None
        assert untouched is not None
        assert [m.author for m in handed.messages] == ["customer", "agent", "customer"]
        assert (handed.status, handed.csat) == ("resolved", 4)
        assert [m.author for m in untouched.messages] == ["customer"]
        assert untouched.status == "open"


async def test_a_simulated_conversation_happens_in_the_simulated_day(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        await seeded(run, tau3_snapshot)
        body = {"scenario": "refund-pressure", "seed": 7, "tick_seconds": 1}
        started = (await run.http.post("/api/sim/start", json=body, headers=OPERATOR)).json()
        await run.queue.run_until_idle()
        day_starts, day_ends = datetime.fromisoformat(started["started_at"]), datetime.fromisoformat(started["ends_at"])
        work = (await run.http.get("/api/work", params={"limit": 50})).json()
        tickets = [item for item in work if item["kind"] == "ticket"]
        assert len(tickets) == 8
        for item in tickets:
            ticket = await run.container.tickets.ticket(str(item["input"]["ticket_id"]))
            assert ticket is not None
            assert {m.author for m in ticket.messages} == {"customer", "agent"}
            times = [m.created_at for m in ticket.messages]
            assert all(day_starts <= at <= day_ends for at in times), ticket.ticket_id
            assert times == sorted(times)
            assert ticket.resolved_at is None or day_starts <= ticket.resolved_at <= day_ends

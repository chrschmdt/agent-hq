from __future__ import annotations

import httpx

from ahq.agents import SUPPORT, version_config
from ahq.app.container import Overrides
from ahq.domain.retail import RetailSnapshot
from ahq.evals.gate import RemoteRun, run_gate
from ahq.evals.scenarios import check_scenario
from tests.conftest import make_settings
from tests.e2e.conftest import OPERATOR, running
from tests.e2e.test_offline_team import RETURN

BRIEFER = version_config(SUPPORT).model_copy(update={"prompt_stable": SUPPORT.prompt.stable + "\n\nBe brief."})


async def test_every_agent_starts_with_its_code_spec_live() -> None:
    async with running() as run:
        versions = (await run.http.get("/api/versions")).json()
        assert sorted((v["version_id"], v["status"]) for v in versions) == [
            ("dispatcher@1", "live"),
            ("insights@1", "live"),
            ("ops@1", "live"),
            ("support@1", "live"),
        ]
        agents = (await run.http.get("/api/agents")).json()
        assert {a["name"]: (a["version"], a["canary"], a["paused"]) for a in agents}["support"] == (
            "support@1",
            None,
            False,
        )


async def test_a_candidate_goes_through_the_gate_and_a_canary() -> None:
    async with running(tool_transport="direct") as run:
        body = {"config": BRIEFER.model_dump(), "note": "Shorter replies."}
        assert (await run.http.post("/api/agents/support/versions", json=body)).status_code == 401
        denied = {"config": {**BRIEFER.model_dump(), "tools": ["analytics_run_sql"]}, "note": "More tools."}
        refused = await run.http.post("/api/agents/support/versions", json=denied, headers=OPERATOR)
        assert refused.status_code == 422
        draft = (await run.http.post("/api/agents/support/versions", json=body, headers=OPERATOR)).json()
        assert (draft["version_id"], draft["status"], draft["parent_id"]) == ("support@2", "draft", "support@1")

        diff = (await run.http.get("/api/versions/support@2/diff")).json()
        assert "+Be brief." in diff["prompt"]
        assert diff["changes"] == []

        early = await run.http.post("/api/versions/support@2/canary", json={"pct": 50}, headers=OPERATOR)
        assert early.status_code == 409
        queued = (await run.http.post("/api/versions/support@2/gate", headers=OPERATOR)).json()
        assert (queued["status"], queued["backend"], queued["params"]["profile"]) == ("queued", "inprocess", "mock")
        await run.queue.run_until_idle()
        finished = (await run.http.get(f"/api/evals/{queued['eval_run_id']}")).json()
        assert (finished["status"], finished["summary"]["passed"]) == ("passed", True)
        cases = (await run.http.get(f"/api/evals/{queued['eval_run_id']}/cases")).json()
        assert {c["version_id"] for c in cases} == {"support@1", "support@2"}
        assert (await run.http.get("/api/versions/support@2")).json()["status"] == "evaluated"

        await run.http.post("/api/versions/support@2/canary", json={"pct": 50}, headers=OPERATOR)
        support = next(a for a in (await run.http.get("/api/agents")).json() if a["name"] == "support")
        assert (support["canary"]["version_id"], support["canary"]["pct"]) == ("support@2", 50)
        back = await run.http.post("/api/versions/support@2/rollback", json={"reason": "Enough."}, headers=OPERATOR)
        assert (back.json()["status"], back.json()["status_reason"]) == ("retired", "rolled back: Enough.")
        events = (await run.http.get("/api/events", params={"limit": 500})).json()
        kinds = [e["kind"] for e in events if e["actor"] != "code"]
        assert [k for k in kinds if k.startswith(("version.", "eval."))] == [
            "version.created",
            "eval.queued",
            "eval.started",
            "version.evaluated",
            "eval.finished",
            "version.canary_started",
            "version.rolled_back",
        ]


async def test_a_paused_agents_work_goes_to_a_person(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        pause = {"reason": "Checking replies."}
        paused = await run.http.post("/api/agents/support/pause", json=pause, headers=OPERATOR)
        assert paused.json()["paused"]
        opened = (await run.http.post("/api/tickets", json={"message": RETURN}, headers=OPERATOR)).json()
        await run.queue.run_until_idle()
        view = (await run.http.get(f"/api/runs/{opened['work_item']['id']}")).json()
        assert view["item"]["status"] == "escalated"
        assert (await run.http.get("/api/limits")).status_code == 401
        limits = (await run.http.get("/api/limits", headers=OPERATOR)).json()
        assert next(a for a in limits["agents"] if a["agent"] == "support")["reason"] == "Checking replies."
        await run.http.post("/api/agents/support/resume", headers=OPERATOR)
        assert not next(a for a in (await run.http.get("/api/agents")).json() if a["name"] == "support")["paused"]


async def test_reviews_are_labeled_blind_and_feed_calibration_and_scorecards(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        opened = (await run.http.post("/api/tickets", json={"message": RETURN}, headers=OPERATOR)).json()
        await run.queue.run_until_idle()
        (pending,) = (await run.http.get("/api/approvals")).json()
        decision = {"verdict": "approve", "note": "Fine."}
        await run.http.post(f"/api/approvals/{pending['id']}/decision", json=decision, headers=OPERATOR)
        await run.queue.run_until_idle()
        work_item_id = opened["work_item"]["id"]
        wanted = {"work_item_id": work_item_id, "agent": "support"}
        assert (await run.http.post("/api/qa/reviews", json=wanted, headers=OPERATOR)).status_code == 202
        await run.queue.run_until_idle()

        [review] = (await run.http.get("/api/qa/reviews", params={"agent": "support"})).json()
        assert review["work_item_id"] == work_item_id
        assert review["reason"] in {"requested", "sample"}, "a run the sample picked keeps its first review"
        [task] = (await run.http.get("/api/qa/queue", params={"agent": "support"})).json()
        assert "verdict" not in str(task["criteria"])
        assert task["material"]["answer"]["status"] == "resolved"
        assert "agent calls return_delivered_order_items" in task["material"]["transcript"]

        verdicts = {"request_handled": "pass", "clear_and_courteous": "pass"}
        body = {"work_item_id": task["work_item_id"], "agent": "support", "verdicts": verdicts}
        assert (await run.http.post("/api/qa/labels", json=body)).status_code == 401
        outcome = (await run.http.post("/api/qa/labels", json=body, headers=OPERATOR)).json()
        assert [label["criterion_id"] for label in outcome["labels"]] == list(verdicts)
        assert {c["criterion_id"] for c in outcome["review"]["criteria"]} >= set(verdicts)
        assert (await run.http.get("/api/qa/queue", params={"agent": "support"})).json() == []

        calibration = (await run.http.get("/api/qa/calibration")).json()
        handled = next(c for c in calibration if c["criterion_id"] == "request_handled")
        assert (handled["current"]["positives"], handled["current"]["calibrated"]) == (1, False)

        cards = (await run.http.get("/api/agents/support/scorecards")).json()
        [live] = [card for card in cards["versions"] if card["version"]["status"] == "live"]
        assert live["scorecard"]["runs"] == 1
        assert live["scorecard"]["metrics"]["resolution_rate"]["value"] == 1.0
        assert live["scorecard"]["metrics"]["approval_rejection_rate"]["samples"] == 1
        assert cards["canary"] is None


async def test_a_bad_deploy_is_rolled_back_before_it_does_much_harm() -> None:
    report = await check_scenario(make_settings(tool_transport="direct"), "bad-deploy", seed=7, trials=1, max_usd=0.1)
    [trial] = report.trials
    assert trial.passed, trial.expectations
    assert trial.expectations[0].detail.startswith("rolled back after")


async def test_a_gate_requested_here_can_run_elsewhere_and_report_back() -> None:
    async with running(tool_transport="direct") as run:
        body = {"config": BRIEFER.model_dump(), "note": "Shorter replies."}
        await run.http.post("/api/agents/support/versions", json=body, headers=OPERATOR)
        requested = await run.container.evals.request("support@2", by="operator", launch=False)
        transport = httpx.ASGITransport(app=run.app)
        remote = RemoteRun("http://testserver", "test-operator-token", requested.eval_run_id, transport=transport)
        loaded, candidate, baseline = await remote.load()
        await remote.started("https://github.com/example/ahq/actions/runs/1")
        result = await run_gate(run.container.settings, loaded, candidate, baseline)
        await remote.report(result, url="https://github.com/example/ahq/actions/runs/1")
        await remote.close()

        finished = (await run.http.get(f"/api/evals/{requested.eval_run_id}")).json()
        assert (finished["status"], finished["backend"], finished["url"]) == (
            "passed",
            "cli",
            "https://github.com/example/ahq/actions/runs/1",
        )
        assert len((await run.http.get(f"/api/evals/{requested.eval_run_id}/cases")).json()) == 6


async def test_the_admin_switches_the_model_profile_and_only_they_see_budgets() -> None:
    async with running() as run:
        models = (await run.http.get("/api/models")).json()
        assert (models["profile"], models["default"], models["switchable"]) == ("mock", "mock", True)
        assert {profile["name"]: profile["available"] for profile in models["profiles"]} == {
            "mock": True,
            "low": False,
            "medium": False,
            "high": False,
        }
        high = next(profile for profile in models["profiles"] if profile["name"] == "high")
        assert high["roles"]["support"] == "claude-opus-5-5"

        assert (await run.http.put("/api/models/profile", json={"profile": "mock"})).status_code == 401
        refused = await run.http.put("/api/models/profile", json={"profile": "high"}, headers=OPERATOR)
        assert refused.status_code == 409
        chosen = (await run.http.put("/api/models/profile", json={"profile": "mock"}, headers=OPERATOR)).json()
        assert (chosen["profile"], chosen["chosen_by"]) == ("mock", "operator")

        agent = (await run.http.get("/api/agents")).json()[0]
        assert "budget_usd" not in agent
        assert "spent_today_usd" not in agent

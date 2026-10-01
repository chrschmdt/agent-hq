from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from ahq.app.container import Overrides
from ahq.domain import WorkStatus
from ahq.domain.retail import RetailSnapshot
from ahq.testing import FakeChatModels
from tests.e2e.conftest import OPERATOR, running
from tests.e2e.test_simulator_api import seeded
from tests.unit.graphs.harness import DRAFT, calls, incident, proposal, proposals, route


def proposing_the_draft(messages: Sequence[BaseMessage]) -> AIMessage:
    drafted = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == DRAFT[0])
    return proposals(proposal(json.loads(str(drafted.content))["draft_id"]))


async def test_a_carrier_delay_ends_in_a_published_notice(tau3_snapshot: RetailSnapshot) -> None:
    models = FakeChatModels()
    models.script("dispatcher", route("ops"))
    models.script(
        "ops",
        incident(
            "insights",
            affected={
                "carrier": "northstar",
                "region": "northeast",
                "category": None,
                "item_id": None,
                "order_ids": [],
            },
        ),
    )
    models.script("insights", calls(DRAFT), proposing_the_draft)
    async with running(Overrides(models=models, store=tau3_snapshot)) as run:
        await seeded(run, tau3_snapshot)
        body = {"scenario": "carrier-delay", "seed": 7, "tick_seconds": 1, "alerts_to_agents": True}
        assert (await run.http.post("/api/sim/start", json=body, headers=OPERATOR)).status_code == 201
        await run.queue.run_until_idle()

        (filed,) = (await run.http.get("/api/incidents")).json()
        assert filed["report"]["affected"]["carrier"] == "northstar"
        assert (await run.container.work.get(filed["work_item_id"])).status is WorkStatus.DONE
        (pending,) = (await run.http.get("/api/proposals", params={"status": "pending"})).json()
        assert pending["incident_id"] == filed["incident_id"]
        draft_id = pending["proposal"]["draft_id"]
        assert (await run.http.get(f"/api/drafts/{draft_id}")).json()["status"] == "pending"

        decision = {"verdict": "approved", "note": "Publish it."}
        path = f"/api/proposals/{pending['proposal_id']}/decision"
        assert (await run.http.post(path, json=decision)).status_code == 401
        decided = await run.http.post(path, json=decision, headers=OPERATOR)
        assert decided.json()["status"] == "approved"
        assert (await run.http.get(f"/api/drafts/{draft_id}")).json()["status"] == "published"
        assert (await run.http.post(path, json=decision, headers=OPERATOR)).status_code == 409

        kinds: set[str] = set()
        cursor = 0
        while page := (await run.http.get("/api/events", params={"after": cursor, "limit": 500})).json():
            kinds.update(event["kind"] for event in page)
            cursor = page[-1]["id"]
        expected = {"kpi.alert", "work.routed", "incident.filed", "agent.handoff", "proposal.created", "kb.published"}
        assert expected <= kinds

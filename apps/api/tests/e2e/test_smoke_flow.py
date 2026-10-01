from __future__ import annotations

import pytest

from tests.e2e.conftest import OPERATOR, running


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
def storage_settings(request: pytest.FixtureRequest) -> dict[str, str]:
    if request.param == "memory":
        return {}
    url: str = request.getfixturevalue("clean_db")
    return {"database_url": url, "database_url_unpooled": url}


async def test_the_smoke_flow_end_to_end(storage_settings: dict[str, str]) -> None:
    async with running(**storage_settings) as run:
        submitted = await run.http.post("/api/work", json={"kind": "smoke"}, headers=OPERATOR)
        assert submitted.status_code == 202
        work_item_id = submitted.json()["id"]
        await run.queue.run_until_idle()

        (approval,) = (await run.http.get("/api/approvals")).json()
        assert approval["work_item_id"] == work_item_id
        assert (await run.http.get("/api/status")).json()["active"] is True

        decided = await run.http.post(
            f"/api/approvals/{approval['id']}/decision", json={"verdict": "approve"}, headers=OPERATOR
        )
        assert decided.json()["status"] == "approved"
        await run.queue.run_until_idle()

        detail = (await run.http.get(f"/api/work/{work_item_id}")).json()
        assert detail["item"]["status"] == "done"
        assert detail["events"][-1]["kind"] == "work.completed"
        assert detail["events"][-1]["payload"] == {"outcome": "approved"}
        assert (await run.http.get("/api/status")).json()["active"] is False


async def test_the_live_stream_replays_from_a_cursor() -> None:
    async with running() as run:
        await run.http.post("/api/work", json={"kind": "smoke"}, headers=OPERATOR)
        await run.queue.run_until_idle()
        response = await run.http.get("/api/events/stream", params={"after": 0})

    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in response.headers["cache-control"], "a proxy that compresses the stream holds it back"
    ids = [int(line.removeprefix("id: ")) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids)
    assert len(ids) >= 5


async def test_the_live_stream_resumes_after_last_event_id() -> None:
    async with running() as run:
        await run.http.post("/api/work", json={"kind": "smoke"}, headers=OPERATOR)
        await run.queue.run_until_idle()
        response = await run.http.get("/api/events/stream", headers={"Last-Event-ID": "3"})

    ids = [int(line.removeprefix("id: ")) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids[0] == 4


async def test_state_changes_need_the_operator_token() -> None:
    async with running() as run:
        anonymous = await run.http.post("/api/work", json={"kind": "smoke"})
        wrong = await run.http.post("/api/work", json={"kind": "smoke"}, headers={"Authorization": "Bearer nope"})
        decision = await run.http.post("/api/approvals/apv_x/decision", json={"verdict": "approve"})
    assert anonymous.status_code == wrong.status_code == decision.status_code == 401


async def test_reads_are_public() -> None:
    async with running() as run:
        for path in ("/api/health", "/api/status", "/api/events", "/api/approvals"):
            assert (await run.http.get(path)).status_code == 200


async def test_deciding_twice_is_a_conflict_and_unknown_ids_are_404() -> None:
    async with running() as run:
        await run.http.post("/api/work", json={"kind": "smoke"}, headers=OPERATOR)
        await run.queue.run_until_idle()
        (approval,) = (await run.http.get("/api/approvals")).json()
        path = f"/api/approvals/{approval['id']}/decision"
        await run.http.post(path, json={"verdict": "reject"}, headers=OPERATOR)
        again = await run.http.post(path, json={"verdict": "approve"}, headers=OPERATOR)
        missing = await run.http.get("/api/work/wi_missing")
    assert again.status_code == 409
    assert again.headers["content-type"] == "application/problem+json"
    assert missing.status_code == 404


async def test_the_cron_endpoint_needs_the_cron_secret() -> None:
    async with running() as run:
        denied = await run.http.get("/api/cron/qdrant-keepalive")
        allowed = await run.http.get("/api/cron/qdrant-keepalive", headers={"Authorization": "Bearer test-cron-secret"})
    assert denied.status_code == 401
    assert allowed.json() == {"collections": 3}

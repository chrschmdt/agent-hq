from __future__ import annotations

import asyncio
import sys

import httpx
import pytest
from langsmith import Client
from pydantic import SecretStr

from ahq.api.factory import create_app
from ahq.app.container import Overrides
from ahq.settings import Settings
from tests.live.conftest import require

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

OPERATOR_TOKEN = "live-operator"


async def test_a_smoke_run_is_traced_end_to_end(live_settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    require(live_settings.openrouter_api_key, "OPENROUTER_API_KEY")
    require(live_settings.langsmith_api_key, "LANGSMITH_API_KEY")
    assert live_settings.langsmith_api_key is not None
    settings = live_settings.model_copy(
        update={
            "model_profile": "medium",
            "queue_backend": "inprocess",
            "tool_transport": "asgi",
            "operator_token": SecretStr(OPERATOR_TOKEN),
        }
    )
    app = create_app(settings, overrides=Overrides(storage="memory"), run_queue_worker=False)
    headers = {"Authorization": f"Bearer {OPERATOR_TOKEN}"}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http,
    ):
        queue = app.state.container.inprocess_queue
        work_item_id = (await http.post("/api/work", json={"kind": "smoke"}, headers=headers)).json()["id"]
        await queue.run_until_idle()
        (approval,) = (await http.get("/api/approvals")).json()
        await http.post(f"/api/approvals/{approval['id']}/decision", json={"verdict": "approve"}, headers=headers)
        await queue.run_until_idle()
        detail = (await http.get(f"/api/work/{work_item_id}")).json()

    assert detail["item"]["status"] == "done"
    model_event = next(event for event in detail["events"] if event["kind"] == "model.called")
    assert model_event["payload"]["model"] == "claude-haiku-4-5"

    client = Client(api_key=live_settings.langsmith_api_key.get_secret_value())
    project = await asyncio.to_thread(client.read_project, project_name=live_settings.langsmith_project)
    query = f'and(eq(metadata_key, "ahq_run_id"), eq(metadata_value, "{work_item_id}"))'
    runs = []
    for _ in range(10):
        runs = [run async for run in client.runs.query(project_ids=[str(project.id)], filter=query, is_root=True)]
        if len(runs) >= 2:
            break
        await asyncio.sleep(3)
    assert len(runs) >= 2
    root = str(runs[0].id)
    link = await client.runs.get_url(root, project_id=str(project.id), trace_id=root)
    with capsys.disabled():
        sys.stdout.write(f"\ntrace: {link.url}\n")

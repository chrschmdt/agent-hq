from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport

from ahq.adapters.mcp_client import HttpToolProvider
from ahq.api.factory import create_app
from ahq.app.mcp import principals
from ahq.mcp_servers import mint_token
from ahq.tools import CONTEXT_ARG, Server, exposed_tools, server_tools
from tests.conftest import make_settings

SECRET = "test-mcp-secret"


@asynccontextmanager
async def running(**settings: Any) -> AsyncIterator[FastAPI]:
    app = create_app(make_settings(mcp_token_secret=SECRET, **settings), run_queue_worker=False)
    async with app.router.lifespan_context(app):
        yield app


def asgi_client_factory(app: FastAPI) -> Callable[..., httpx2.AsyncClient]:
    def factory(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), **kwargs)

    return factory


def provider(app: FastAPI, server_secret: str = SECRET) -> HttpToolProvider:
    return HttpToolProvider(
        "http://testserver",
        lambda server, subject: mint_token(server_secret, server, subject),
        client_factory=asgi_client_factory(app),
    )


async def listed(app: FastAPI, server: str, subject: str) -> dict[str, dict[str, Any]]:
    transport = StreamableHttpTransport(
        f"http://testserver/mcp/{server}",
        auth=mint_token(SECRET, server, subject),
        httpx_client_factory=asgi_client_factory(app),
    )
    async with Client(transport) as client:
        return {tool.name: tool.input_schema for tool in await client.list_tools()}


async def test_agents_call_tools_over_http() -> None:
    async with running() as app:
        result = await provider(app).call("agents", "smoke", "echo", {"text": "over http"})
    assert result.output == "over http"


async def test_a_token_minted_with_another_secret_cannot_call_tools() -> None:
    async with running() as app:
        with pytest.raises(Exception, match="error response"):
            await provider(app, server_secret="wrong-secret").call("agents", "smoke", "echo", {"text": "no"})


@pytest.mark.parametrize("subject", ["support", "operator"])
@pytest.mark.parametrize("server", ["orders", "knowledge"])
async def test_each_caller_sees_exactly_its_tools_with_the_catalogs_schemas(server: Server, subject: str) -> None:
    principal = principals()[subject]
    async with running() as app:
        tools = await listed(app, server, subject)
    expected = exposed_tools(principal, server_tools(server))
    assert set(tools) == {spec.name for spec in expected}
    for spec in expected:
        catalog = spec.model_schema()["function"]["parameters"]  # type: ignore[index]
        properties = dict(tools[spec.name]["properties"])
        assert properties.pop(CONTEXT_ARG)["default"] is None
        assert properties.keys() == catalog["properties"].keys()  # type: ignore[index]
        assert set(tools[spec.name].get("required", [])) == set(catalog.get("required", []))  # type: ignore[union-attr]


async def test_the_operator_reads_the_store_and_cannot_change_it() -> None:
    async with running() as app:
        tools = provider(app)
        found = await tools.call("operator", "orders", "list_all_product_types", {})
        write = await tools.call("operator", "orders", "cancel_pending_order", {"order_id": "#W1", "reason": "no"})
    assert found.ok
    assert write.output == "Error: Tool 'cancel_pending_order' not found."


async def test_requests_without_a_token_get_401() -> None:
    async with (
        running() as app,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http,
    ):
        response = await http.post("/mcp/smoke", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


async def test_unknown_hosts_are_refused() -> None:
    token = mint_token(SECRET, "smoke", "agents")
    async with (
        running() as app,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evil.example") as http,
    ):
        response = await http.post(
            "/mcp/smoke",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code in {400, 403, 421}


async def test_on_vercel_any_routed_domain_is_served() -> None:
    token = mint_token(SECRET, "smoke", "agents")
    async with (
        running(vercel_url="ahq-abc123.vercel.app") as app,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://ahq.example.com") as http,
    ):
        response = await http.post(
            "/mcp/smoke",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200

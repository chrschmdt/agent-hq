from __future__ import annotations

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ahq.mcp_servers import BearerAuth, mint_token

SECRET = "test-secret"


def endpoint(name: str) -> Starlette:
    async def whoami(request: Request) -> JSONResponse:
        return JSONResponse({"endpoint": name, "subject": request.scope["state"]["mcp_subject"]})

    return Starlette(routes=[Route("/", whoami)])


def client() -> httpx.AsyncClient:
    app = BearerAuth({"agents": endpoint("a"), "operator": endpoint("o")}, server="orders", secret=SECRET)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def test_tokens_differ_by_server_and_subject() -> None:
    tokens = {mint_token(SECRET, server, subject) for server in ("orders", "knowledge") for subject in ("a", "b")}
    assert len(tokens) == 4


async def test_a_valid_token_reaches_its_subjects_server() -> None:
    async with client() as http:
        agents = await http.get("/", headers={"Authorization": f"Bearer {mint_token(SECRET, 'orders', 'agents')}"})
        operator = await http.get("/", headers={"Authorization": f"Bearer {mint_token(SECRET, 'orders', 'operator')}"})
    assert agents.json() == {"endpoint": "a", "subject": "agents"}
    assert operator.json() == {"endpoint": "o", "subject": "operator"}


async def test_missing_or_foreign_tokens_are_rejected() -> None:
    other_server = mint_token(SECRET, "knowledge", "agents")
    async with client() as http:
        missing = await http.get("/")
        foreign = await http.get("/", headers={"Authorization": f"Bearer {other_server}"})
    assert missing.status_code == 401
    assert foreign.status_code == 401
    assert missing.headers["www-authenticate"].startswith("Bearer")


async def test_tokens_that_are_not_text_are_rejected_not_errors() -> None:
    async with client() as http:
        accented = await http.get("/", headers={b"Authorization": b"Bearer ahq_\xc3\xa9"})
        undecodable = await http.get("/", headers={b"Authorization": b"Bearer \xff\xfe"})
    assert accented.status_code == 401
    assert undecodable.status_code == 401

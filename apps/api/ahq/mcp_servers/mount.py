from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route
from starlette.types import ASGIApp

from ahq.mcp_servers.auth import BearerAuth

LOCAL_HOSTS = ("localhost", "127.0.0.1", "testserver")
UNAUTHENTICATED_SUBJECT = "operator"


@dataclass(frozen=True)
class McpMount:
    name: str
    servers: Mapping[str, MCPServer]
    route: Route


def transport_security(*, check_hosts: bool) -> TransportSecuritySettings:
    if not check_hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts = [f"{host}:*" for host in LOCAL_HOSTS] + list(LOCAL_HOSTS)
    origins = [f"http://{host}:*" for host in LOCAL_HOSTS]
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def build_mounts(
    servers: Mapping[str, Mapping[str, MCPServer]],
    *,
    token_secret: str | None,
    check_hosts: bool = True,
) -> list[McpMount]:
    security = transport_security(check_hosts=check_hosts)
    apps: dict[int, ASGIApp] = {}
    mounts: list[McpMount] = []
    for name, by_subject in servers.items():
        path = f"/mcp/{name}"
        endpoints: dict[str, ASGIApp] = {}
        for subject, server in by_subject.items():
            if id(server) not in apps:
                apps[id(server)] = _endpoint(server, path, security)
            endpoints[subject] = apps[id(server)]
        if token_secret:
            endpoint: ASGIApp = BearerAuth(endpoints, server=name, secret=token_secret)
        else:
            endpoint = endpoints.get(UNAUTHENTICATED_SUBJECT) or next(iter(endpoints.values()))
        mounts.append(McpMount(name=name, servers=dict(by_subject), route=Route(path, endpoint=endpoint)))
    return mounts


def _endpoint(server: MCPServer, path: str, security: TransportSecuritySettings) -> ASGIApp:
    app = server.streamable_http_app(
        streamable_http_path=path,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    (route,) = (route for route in app.routes if isinstance(route, Route) and route.path == path)
    return route.app


@asynccontextmanager
async def run_mounts(mounts: Iterable[McpMount]) -> AsyncIterator[None]:
    unique = {id(server): server for mount in mounts for server in mount.servers.values()}
    async with AsyncExitStack() as stack:
        for server in unique.values():
            await stack.enter_async_context(server.session_manager.run())
        yield

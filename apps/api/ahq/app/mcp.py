from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mcp.server import MCPServer

from ahq.agents import SPECS, principal_for
from ahq.mcp_servers import McpMount, build_mounts, build_smoke_server, build_tool_server
from ahq.ports import Clock
from ahq.settings import Settings
from ahq.tools import OPERATOR, SERVERS, Principal, ToolExecutor

SMOKE_SUBJECT = "agents"


def principals() -> dict[str, Principal]:
    agents = {spec.name: principal_for(spec) for spec in SPECS.values() if spec.tools}
    return {**agents, OPERATOR.subject: OPERATOR}


@dataclass(frozen=True)
class McpBundle:
    servers: dict[str, dict[str, MCPServer]]
    mounts: list[McpMount]


def build_mcp(settings: Settings, clock: Clock, executor: ToolExecutor, callers: Mapping[str, Principal]) -> McpBundle:
    smoke = build_smoke_server(clock)
    servers: dict[str, dict[str, MCPServer]] = {"smoke": {SMOKE_SUBJECT: smoke, OPERATOR.subject: smoke}}
    for server in SERVERS:
        servers[server] = {
            subject: build_tool_server(server, principal, executor) for subject, principal in callers.items()
        }
    secret = settings.mcp_token_secret.get_secret_value() if settings.mcp_token_secret else None
    if secret is None and settings.is_deployed:
        raise RuntimeError("AHQ_MCP_TOKEN_SECRET must be set on deployed environments")
    mounts = build_mounts(servers, token_secret=secret, check_hosts=not settings.is_vercel)
    return McpBundle(servers=servers, mounts=mounts)

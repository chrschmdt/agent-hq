from __future__ import annotations

from mcp.server import MCPServer

from ahq.ports import Clock


def build_smoke_server(clock: Clock) -> MCPServer:
    server = MCPServer(
        name="ahq-smoke",
        instructions="Diagnostic tools used to check that agents can reach AHQ's MCP servers.",
    )

    @server.tool(name="echo", description="Return the given text unchanged. Used to check that tool calls work.")
    def echo(text: str) -> str:
        return text

    @server.tool(name="now", description="Return the server's current time as an ISO 8601 string.")
    def now() -> str:
        return clock.now().isoformat()

    return server

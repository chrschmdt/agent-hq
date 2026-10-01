from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from typing import Any

from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from langchain_core._api import LangChainBetaWarning
from langchain_core.tools import BaseTool
from mcp.server import MCPServer
from mcp.shared._httpx_utils import McpHttpClientFactory

from ahq.domain import NotFoundError, ToolResult

with warnings.catch_warnings():
    warnings.simplefilter("ignore", LangChainBetaWarning)
    from langchain.mcp import MCPAdapter


def tool_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "".join(block.get("text", "") for block in result if isinstance(block, dict))
    return str(result)


class _ToolCache:
    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], dict[str, BaseTool]] = {}

    async def call(
        self, key: tuple[str, str], load: Callable[[], Any], tool: str, arguments: Mapping[str, Any]
    ) -> ToolResult:
        if key not in self._tools:
            async with load() as adapter:
                self._tools[key] = {t.name: t for t in await adapter.list_tools()}
        found = self._tools[key].get(tool)
        if found is None:
            return ToolResult.error(f"Tool '{tool}' not found.")
        return ToolResult(output=tool_text(await found.ainvoke(dict(arguments))))


class InProcessToolProvider:
    def __init__(self, servers: Mapping[str, Mapping[str, MCPServer]]) -> None:
        self._servers = {name: dict(by_subject) for name, by_subject in servers.items()}
        self._cache = _ToolCache()

    async def call(self, subject: str, server: str, tool: str, arguments: Mapping[str, Any]) -> ToolResult:
        target = self._servers.get(server, {}).get(subject)
        if target is None:
            raise NotFoundError(f"no MCP server {server!r} for {subject!r}")
        return await self._cache.call((subject, server), lambda: MCPAdapter(target), tool, arguments)


class HttpToolProvider:
    def __init__(
        self,
        base_url: str,
        token_for: Callable[[str, str], str],
        *,
        timeout_seconds: float = 30.0,
        headers: Mapping[str, str] | None = None,
        client_factory: McpHttpClientFactory | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token_for = token_for
        self._timeout = timeout_seconds
        self._headers = dict(headers or {})
        self._client_factory = client_factory
        self._cache = _ToolCache()

    def url(self, server: str) -> str:
        return f"{self._base_url}/mcp/{server}"

    async def call(self, subject: str, server: str, tool: str, arguments: Mapping[str, Any]) -> ToolResult:
        def connect() -> MCPAdapter:
            transport = StreamableHttpTransport(
                self.url(server),
                headers=self._headers,
                auth=self._token_for(server, subject),
                httpx_client_factory=self._client_factory,
            )
            return MCPAdapter(Client(transport, timeout=self._timeout))

        return await self._cache.call((subject, server), connect, tool, arguments)

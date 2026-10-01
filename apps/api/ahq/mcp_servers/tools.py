from __future__ import annotations

import inspect
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from ahq.domain import Effect
from ahq.tools import CONTEXT_ARG, Principal, Server, ToolExecutor, ToolSpec, exposed_tools, server_tools

INSTRUCTIONS = {
    "orders": "The store's customers, products and orders: look them up, and change them within policy.",
    "knowledge": "The store's knowledge base: policies, help articles, shipping information and product guides.",
    "analytics": "Read-only questions of the store: KPIs, SQL, similar tickets, ticket clusters, recent changes.",
}


def build_tool_server(server: Server, principal: Principal, executor: ToolExecutor) -> MCPServer:
    mcp = MCPServer(name=f"ahq-{server}", instructions=INSTRUCTIONS[server])
    for spec in exposed_tools(principal, server_tools(server)):
        mcp.add_tool(
            _tool_function(spec, principal, executor),
            name=spec.name,
            description=spec.description,
            annotations=ToolAnnotations(read_only_hint=spec.effect is Effect.READ, open_world_hint=False),
            structured_output=False,
        )
    return mcp


def _tool_function(spec: ToolSpec, principal: Principal, executor: ToolExecutor) -> Any:
    async def call(**arguments: Any) -> str:
        return (await executor.call(principal, spec.name, arguments)).output

    parameters = [
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=field.annotation, default=field)
        for name, field in spec.args.model_fields.items()
    ]
    parameters.append(
        inspect.Parameter(CONTEXT_ARG, inspect.Parameter.KEYWORD_ONLY, annotation=str | None, default=None)
    )
    call.__signature__ = inspect.Signature(parameters, return_annotation=str)  # type: ignore[attr-defined]
    call.__name__ = spec.name
    return call

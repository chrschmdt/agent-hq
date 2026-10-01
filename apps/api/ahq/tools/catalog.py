from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ahq.tools.analytics import ANALYTICS_TOOLS
from ahq.tools.knowledge import KNOWLEDGE_TOOLS
from ahq.tools.orders import ORDERS_TOOLS
from ahq.tools.types import Autonomy, Principal, Server, ToolSpec

CATALOG: Mapping[str, ToolSpec] = MappingProxyType(
    {spec.name: spec for spec in (*ORDERS_TOOLS, *KNOWLEDGE_TOOLS, *ANALYTICS_TOOLS)}
)
SERVERS: tuple[Server, ...] = ("orders", "knowledge", "analytics")

OPERATOR = Principal(
    subject="operator",
    autonomy=Autonomy.OBSERVE,
    tools=frozenset(CATALOG),
    customer_scoped=False,
    audience="internal",
)


def server_tools(server: Server) -> list[ToolSpec]:
    return [spec for spec in CATALOG.values() if spec.server == server]

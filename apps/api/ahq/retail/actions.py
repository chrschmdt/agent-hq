from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import BaseModel

from ahq.retail.service import RetailService
from ahq.retail.types import ActionOutcome, RetailError, format_output

TOOL_NAMES = (
    "calculate",
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_item_details",
    "get_order_details",
    "get_product_details",
    "get_user_details",
    "list_all_product_types",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "transfer_to_human_agents",
)
STORE_TOOL_NAMES = ("issue_refund",)


async def run_action(service: RetailService, name: str, arguments: Mapping[str, Any]) -> ActionOutcome:
    if name not in TOOL_NAMES and name not in STORE_TOOL_NAMES:
        return ActionOutcome(output=f"Error: Tool '{name}' not found.", error=True)
    tool: Callable[..., Awaitable[BaseModel | str]] = getattr(service, name)
    try:
        result = await tool(**arguments)
    except (RetailError, TypeError) as error:
        return ActionOutcome(output=f"Error: {error}", error=True)
    return ActionOutcome(output=format_output(result))

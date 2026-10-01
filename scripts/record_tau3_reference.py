from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tau2.domains.retail.data_model import GiftCard, Order, OrderPayment, RetailDB
from tau2.domains.retail.tools import RetailTools
from tau2.environment.environment import Environment
from tau2.utils.utils import get_dict_hash

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "tau3" / "v1.0.1"
OUTPUT = ROOT / "apps" / "api" / "tests" / "fixtures" / "tau3" / "reference_replays.jsonl"


def modify_pending_order_items_fixed(
    self: RetailTools, order_id: str, item_ids: list[str], new_item_ids: list[str], payment_method_id: str
) -> Order:
    order = self._get_order(order_id)
    if order.status != "pending":
        raise ValueError("Non-pending order cannot be modified")
    all_item_ids = [item.item_id for item in order.items]
    for item_id in item_ids:
        if item_ids.count(item_id) > all_item_ids.count(item_id):
            raise ValueError(f"{item_id} not found")
    if len(item_ids) != len(new_item_ids):
        raise ValueError("The number of items to be exchanged should match")
    diff_price = 0
    variants = []
    for item_id, new_item_id in zip(item_ids, new_item_ids, strict=True):
        if item_id == new_item_id:
            raise ValueError("The new item id should be different from the old item id")
        item = next((item for item in order.items if item.item_id == item_id), None)
        if item is None:
            raise ValueError(f"Item {item_id} not found")
        variant = self._get_variant(item.product_id, new_item_id)
        if not variant.available:
            raise ValueError(f"New item {new_item_id} not found or available")
        variants.append(variant)
        diff_price += variant.price - item.price
    payment_method = self._get_payment_method(order.user_id, payment_method_id)
    if isinstance(payment_method, GiftCard) and payment_method.balance < diff_price:
        raise ValueError("Insufficient gift card balance to pay for the new item")
    order.payment_history.append(
        OrderPayment(
            transaction_type="payment" if diff_price > 0 else "refund",
            amount=abs(diff_price),
            payment_method_id=payment_method_id,
        )
    )
    if isinstance(payment_method, GiftCard):
        payment_method.balance -= diff_price
        payment_method.balance = round(payment_method.balance, 2)
    for item_id, variant in zip(item_ids, variants, strict=True):
        item = next(item for item in order.items if item.item_id == item_id)
        item.item_id = variant.item_id
        item.price = variant.price
        item.options = variant.options
    order.status = "pending (item modified)"
    return order


def replay(raw_db: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    tools = RetailTools(RetailDB.model_validate(raw_db))
    outputs = []
    for action in actions:
        try:
            result = tools.use_tool(action["name"], **action["arguments"])
            outputs.append({"output": Environment.to_json_str(result), "error": False})
        except Exception as error:
            outputs.append({"output": f"Error: {error}", "error": True})
    return {"outputs": outputs, "final_hash": get_dict_hash(tools.db.model_dump())}


def main() -> int:
    raw_db = json.loads((DATA / "db.json").read_text())
    tasks = json.loads((DATA / "tasks.json").read_text())
    initial_hash = get_dict_hash(RetailDB.model_validate(raw_db).model_dump())
    upstream_items = RetailTools.modify_pending_order_items
    records = []
    for task in tasks:
        actions = task["evaluation_criteria"].get("actions") or []
        RetailTools.modify_pending_order_items = upstream_items
        upstream = replay(raw_db, actions)
        RetailTools.modify_pending_order_items = modify_pending_order_items_fixed
        patched = replay(raw_db, actions)
        records.append({"task_id": task["id"], "initial_hash": initial_hash, "upstream": upstream, "patched": patched})
    RetailTools.modify_pending_order_items = upstream_items
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
    changed = sum(record["upstream"]["final_hash"] != record["patched"]["final_hash"] for record in records)
    sys.stdout.write(f"recorded {len(records)} tasks to {OUTPUT.relative_to(ROOT)}; the fix changes {changed}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

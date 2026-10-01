"""Smoke-test a running AHQ deployment end to end.

Checks health, both backing services, MCP over HTTP, a full smoke run with an approval, and the SSE stream.

    cd apps/api && uv run python ../../scripts/smoke.py --base-url https://<deployment>

Reads AHQ_OPERATOR_TOKEN, AHQ_MCP_TOKEN_SECRET and, for protected deployments,
VERCEL_AUTOMATION_BYPASS_SECRET from the environment or `.env`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ahq.adapters.mcp_client import HttpToolProvider
from ahq.mcp_servers import mint_token
from ahq.settings import Settings

POLL_SECONDS = 2.0
TIMEOUT_SECONDS = 180.0


class Failed(Exception):
    pass
def report(name: str, ok: bool, detail: str) -> None:
    sys.stdout.write(f"{'PASS' if ok else 'FAIL'}  {name:<22} {detail}\n")


async def poll(check: Callable[[], Awaitable[Any]], what: str) -> Any:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = await check()
        if result:
            return result
        await asyncio.sleep(POLL_SECONDS)
    raise Failed(f"timed out waiting for {what}")


async def run(base_url: str, settings: Settings) -> bool:
    if settings.operator_token is None or settings.mcp_token_secret is None:
        raise Failed("AHQ_OPERATOR_TOKEN and AHQ_MCP_TOKEN_SECRET must be set")
    common = settings.self_headers
    operator = {**common, "Authorization": f"Bearer {settings.operator_token.get_secret_value()}"}
    passed = True
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0, headers=common) as http:
        health = (await http.get("/api/health")).json()
        report("health", health.get("status") == "ok", str(health))

        deep = (await http.get("/api/health/deep")).json()
        ok = deep == {"database": True, "qdrant": True}
        passed &= ok
        report("database and qdrant", ok, str(deep))

        secret = settings.mcp_token_secret.get_secret_value()
        tools = HttpToolProvider(base_url, lambda server, subject: mint_token(secret, server, subject), headers=common)
        try:
            echoed = await tools.call("operator", "smoke", "echo", {"text": "smoke"})
            products = await tools.call("operator", "orders", "list_all_product_types", {})
        except Exception as error:
            passed = False
            report("mcp over http", False, f"{type(error).__name__}: {error}")
        else:
            count = len(json.loads(products.output)) if products.ok else 0
            ok = echoed.output == "smoke" and count == 50
            passed &= ok
            report("mcp over http", ok, f"echo, orders: {count} product types")

        submitted = await http.post("/api/work", json={"kind": "smoke"}, headers=operator)
        submitted.raise_for_status()
        work_item_id = submitted.json()["id"]
        report("submit work", True, work_item_id)

        async def pending_approval() -> dict[str, Any] | None:
            approvals = (await http.get("/api/approvals")).json()
            return next((a for a in approvals if a["work_item_id"] == work_item_id), None)

        approval = await poll(pending_approval, "the approval")
        report("paused for approval", True, approval["id"])

        decided = await http.post(
            f"/api/approvals/{approval['id']}/decision", json={"verdict": "approve"}, headers=operator
        )
        decided.raise_for_status()

        async def finished() -> dict[str, Any] | None:
            detail = (await http.get(f"/api/work/{work_item_id}")).json()
            return detail if detail["item"]["status"] in {"done", "failed"} else None

        detail = await poll(finished, "the run to finish")
        ok = detail["item"]["status"] == "done"
        passed &= ok
        kinds = [event["kind"] for event in detail["events"]]
        report("resumed and finished", ok, " > ".join(kinds))

        model = next((event["payload"] for event in detail["events"] if event["kind"] == "model.called"), {})
        report("model call", bool(model), f"{model.get('model')} ${float(model.get('cost_usd', 0)):.5f}")

        first_id = detail["events"][0]["id"] - 1
        ids: list[int] = []
        async with http.stream("GET", "/api/events/stream", params={"after": first_id}) as stream:
            async for line in stream.aiter_lines():
                if line.startswith("id: "):
                    ids.append(int(line.removeprefix("id: ")))
                if len(ids) >= len(kinds):
                    break
        ok = ids == sorted(ids) and len(ids) >= len(kinds)
        passed &= ok
        report("sse stream", ok, f"{len(ids)} events replayed in order")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        ok = asyncio.run(run(args.base_url.rstrip("/"), Settings()))
    except Failed as error:
        report("smoke", False, str(error))
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

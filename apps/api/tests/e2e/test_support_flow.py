from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from pydantic import JsonValue

from ahq.app.container import Overrides
from ahq.domain import CustomerTurnJob, WorkStatus
from ahq.domain.retail import Order, RetailSnapshot
from ahq.domain.world import TicketMessage
from ahq.sim.customer import GREETING, scenario
from ahq.testing import FakeChatModels
from tests.e2e.conftest import OPERATOR, Running, running


def calls(*pairs: tuple[str, dict[str, Any]], start: int = 1) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{start + i}", "type": "tool_call"}
            for i, (name, args) in enumerate(pairs)
        ],
    )


def reply(text: str, *, citations: Sequence[str] = (), status: str = "awaiting_customer") -> AIMessage:
    return AIMessage(
        content=json.dumps({"reply": text, "citations": list(citations), "status": status, "summary": text})
    )


def citing_the_search(messages: Sequence[BaseMessage]) -> AIMessage:
    found = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "knowledge_search")
    return reply("Refunds go back to the original payment method.", citations=[json.loads(str(found.content))[0]["id"]])


def a_big_delivered_order(store: RetailSnapshot) -> Order:
    return next(o for o in store.orders.values() if o.status == "delivered" and sum(i.price for i in o.items) > 150)


async def open_ticket(run: Running, text: str) -> dict[str, Any]:
    response = await run.http.post("/api/tickets", json={"message": text}, headers=OPERATOR)
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_ticket_is_answered_with_a_citation_and_closed_after_the_customer_replies(
    tau3_snapshot: RetailSnapshot,
) -> None:
    models = FakeChatModels()
    models.script(
        "support",
        calls(("knowledge_search", {"query": "where does my refund go"})),
        citing_the_search,
        reply("Glad I could help.", status="resolved"),
    )
    async with running(Overrides(models=models, store=tau3_snapshot)) as run:
        opened = await open_ticket(run, "Where does a refund go?")
        await run.queue.run_until_idle()
        work_id, ticket_id = opened["work_item"]["id"], opened["ticket"]["ticket_id"]
        assert (await run.container.work.get(work_id)).status is WorkStatus.WAITING_CUSTOMER
        ticket = (await run.http.get(f"/api/tickets/{ticket_id}")).json()
        assert [m["author"] for m in ticket["messages"]] == ["customer", "agent"]

        written = await run.http.post(f"/api/work/{work_id}/messages", json={"text": "Thanks!"}, headers=OPERATOR)
        assert written.json() == {"position": 2}
        await run.queue.run_until_idle()
        assert (await run.container.work.get(work_id)).status is WorkStatus.DONE
        ticket = (await run.http.get(f"/api/tickets/{ticket_id}")).json()
        assert ticket["status"] == "resolved"
        events = (await run.http.get("/api/events")).json()
        replied = [e for e in events if e["kind"] == "ticket.replied"]
        assert replied[0]["payload"]["citations"]


async def test_a_refund_over_the_limit_waits_in_the_inbox_and_runs_once_approved(tau3_snapshot: RetailSnapshot) -> None:
    order = a_big_delivered_order(tau3_snapshot)
    customer = tau3_snapshot.users[order.user_id]
    items = [item.item_id for item in order.items]
    refund = (
        "return_delivered_order_items",
        {
            "order_id": order.order_id,
            "item_ids": items,
            "payment_method_id": order.payment_history[0].payment_method_id,
        },
    )
    models = FakeChatModels()
    models.script(
        "support",
        calls(("find_user_id_by_email", {"email": customer.email})),
        calls(refund, start=2),
        reply("Your return is requested.", status="resolved"),
    )
    async with running(Overrides(models=models, store=tau3_snapshot), duplicate_deliveries=True) as run:
        opened = await open_ticket(run, f"Please return everything from {order.order_id}.")
        await run.queue.run_until_idle()
        (approval,) = (await run.http.get("/api/approvals")).json()
        assert approval["request"]["action"] == "return_delivered_order_items"
        assert approval["request"]["cost_usd"] > 100
        assert (await run.container.retail.snapshot()).orders[order.order_id].status == "delivered"

        decided = await run.http.post(
            f"/api/approvals/{approval['id']}/decision", json={"verdict": "approve"}, headers=OPERATOR
        )
        assert decided.status_code == 200
        await run.queue.run_until_idle()
        assert (await run.container.work.get(opened["work_item"]["id"])).status is WorkStatus.DONE
        assert (await run.container.retail.snapshot()).orders[order.order_id].status == "return requested"
        record = await run.container.retail.recorded_call(f"th_{opened['work_item']['id']}:call_2")
        assert record is not None
        assert record.approval_id == approval["id"]
        ticket = await run.container.tickets.ticket(opened["ticket"]["ticket_id"])
        assert ticket is not None
        assert [m.author for m in ticket.messages] == ["customer", "agent"]


async def test_cancelled_work_stops_for_good(tau3_snapshot: RetailSnapshot) -> None:
    models = FakeChatModels()
    models.script("support", reply("One moment."))
    async with running(Overrides(models=models, store=tau3_snapshot)) as run:
        opened = await open_ticket(run, "Hello")
        work_id = opened["work_item"]["id"]
        cancelled = await run.http.post(
            f"/api/work/{work_id}/cancel", json={"reason": "opened by mistake"}, headers=OPERATOR
        )
        assert cancelled.json()["status"] == "cancelled"
        await run.queue.run_until_idle()
        assert (await run.container.work.get(work_id)).status is WorkStatus.CANCELLED
        assert len(models.chat("support").calls) == 0  # type: ignore[attr-defined]
        again = await run.http.post(f"/api/work/{work_id}/cancel", json={"reason": "again"}, headers=OPERATOR)
        assert again.status_code == 409


async def test_a_simulated_customer_talks_until_done_and_rates_the_chat(tau3_snapshot: RetailSnapshot) -> None:
    models = FakeChatModels()
    customer = models.script(
        "customer",
        "Hi, where does a refund go?",
        "Great, that is all. ###STOP###",
        json.dumps({"score": 5, "reason": "Quick and clear."}),
    )
    models.script("support", reply("To your original payment method. Anything else?"))
    async with running(Overrides(models=models, store=tau3_snapshot)) as run:
        greeting = TicketMessage(author="agent", body=GREETING, created_at=run.container.clock.now())
        brief: dict[str, JsonValue] = {
            "scenario": scenario("You want to know about refunds.", "Nothing.", "Nothing.", "Be brief.")
        }
        ticket, item = await run.container.commands.open_ticket(
            [greeting], actor="eval", subject="Refunds", brief=brief, wait_for_customer=True
        )
        await run.queue.send(CustomerTurnJob(work_item_id=item.id, position=1))
        await run.queue.run_until_idle()

        final = await run.container.tickets.ticket(ticket.ticket_id)
        assert final is not None
        assert [(m.author, m.body) for m in final.messages] == [
            ("agent", GREETING),
            ("customer", "Hi, where does a refund go?"),
            ("agent", "To your original payment method. Anything else?"),
            ("customer", "Great, that is all."),
        ]
        assert (final.status, final.csat) == ("resolved", 5)
        assert (await run.container.work.get(item.id)).status is WorkStatus.DONE
        first_customer_view = customer.calls[0]
        assert isinstance(first_customer_view[0], SystemMessage)
        assert "<scenario>" in str(first_customer_view[0].content)

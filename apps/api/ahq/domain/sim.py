from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue

from ahq.domain.base import StrictModel

SimStatus = Literal["running", "paused", "finished", "stopped"]
BriefIntent = Literal[
    "where_is_my_order",
    "cancel_order",
    "change_order_address",
    "change_order_items",
    "change_payment",
    "return_items",
    "exchange_items",
    "update_account_address",
    "product_question",
    "refund_status",
    "talk_to_human",
    "refund_pressure",
    "defect_complaint",
    "return_question",
    "attack",
]


class SimRun(StrictModel):
    run_id: str
    scenario: str
    seed: int
    status: SimStatus
    started_at: AwareDatetime
    ends_at: AwareDatetime
    sim_now: AwareDatetime
    tick_no: int = Field(ge=0)
    tick_minutes: int = Field(gt=0)
    tick_seconds: float = Field(ge=0)
    agent_tickets: int = Field(default=0, ge=0)
    alerts_to_agents: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @property
    def tick(self) -> timedelta:
        return timedelta(minutes=self.tick_minutes)


class ExpectedAction(StrictModel):
    name: str
    arguments: dict[str, JsonValue]


class CustomerBrief(StrictModel):
    brief_id: str
    intent: BriefIntent
    user_id: str
    order_id: str | None = None
    product_id: str | None = None
    subject: str
    opening_message: str
    reason_for_call: str
    known_info: str
    unknown_info: str
    task_instructions: str
    expected_actions: tuple[ExpectedAction, ...] = ()


class TicketOpened(StrictModel):
    kind: Literal["ticket.opened"] = "ticket.opened"
    ticket_id: str
    brief: CustomerBrief
    for_agents: bool = False


class ParcelDelivered(StrictModel):
    kind: Literal["parcel.delivered"] = "parcel.delivered"
    tracking_id: str
    order_id: str


class OrderShipped(StrictModel):
    kind: Literal["order.shipped"] = "order.shipped"
    order_id: str
    tracking_id: str
    carrier: str


class ArticlePublished(StrictModel):
    kind: Literal["article.published"] = "article.published"
    doc_id: str
    version: int = Field(ge=1)


class DayEnded(StrictModel):
    kind: Literal["day.ended"] = "day.ended"


ScriptEffect = Annotated[
    TicketOpened | ParcelDelivered | OrderShipped | ArticlePublished | DayEnded, Field(discriminator="kind")
]


class ScriptEntry(StrictModel):
    seq: int = Field(ge=0)
    due_at: AwareDatetime
    effect: ScriptEffect

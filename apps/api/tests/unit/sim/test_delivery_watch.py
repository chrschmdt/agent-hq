from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ahq.domain import EventKind, KpiAlert, WorkItem
from ahq.domain.sim import ParcelDelivered, TicketOpened
from ahq.domain.world import Shipment, Ticket
from ahq.sim.control import SimControl
from ahq.sim.monitor import check_times, delivery_alerts
from ahq.sim.scenarios import CARRIER_DELAY
from tests.unit.sim.test_simulator import Simulator, sim  # noqa: F401 (fixture)

AT = datetime(2026, 6, 15, 16, 0, tzinfo=UTC)
STORE_TIME = ZoneInfo("America/New_York")


def shipment(n: int, carrier: str, region: str) -> Shipment:
    return Shipment(
        tracking_id=f"t{n}",
        order_id=f"#W{n}",
        carrier=carrier,
        state="NY",
        region=region,
        status="in_transit",
        shipped_at=AT - timedelta(days=2),
        promised_at=AT + timedelta(days=3),
    )


def asking(n: int, minutes_ago: int) -> Ticket:
    return Ticket(
        ticket_id=f"tk_{n}",
        user_id="u",
        order_id=f"#W{n}",
        intent="where_is_my_order",
        subject="Where is it?",
        status="open",
        source="simulation",
        created_at=AT - timedelta(minutes=minutes_ago),
    )


PARCELS = [shipment(n, "northstar" if n < 10 else "swiftline", "northeast" if n < 10 else "west") for n in range(40)]


def test_the_watch_runs_on_each_whole_hour() -> None:
    start = datetime(2026, 6, 15, 12, 55, tzinfo=UTC)
    assert list(check_times(start, start + timedelta(minutes=5))) == [datetime(2026, 6, 15, 13, tzinfo=UTC)]
    assert list(check_times(start, start + timedelta(minutes=4))) == []
    assert len(list(check_times(start, start + timedelta(hours=3)))) == 3


def test_a_segment_asking_far_more_than_its_share_raises_an_alert() -> None:
    tickets = [asking(n, 30 + n) for n in range(5)] + [asking(n, 20) for n in (10, 11, 12)]
    (alert,) = delivery_alerts(tickets, PARCELS, AT)
    assert alert.segment == {"carrier": "northstar", "region": "northeast"}
    assert alert.value == 5
    assert alert.samples == 8
    assert alert.baseline == 1.0
    assert alert.detected_at == AT


def test_a_segment_asking_in_line_with_its_share_raises_nothing() -> None:
    tickets = [asking(n, 30) for n in (1, 2)] + [asking(n, 30) for n in range(10, 16)]
    assert delivery_alerts(tickets, PARCELS, AT) == []


def test_tickets_older_than_the_window_do_not_count() -> None:
    tickets = [asking(n, 200 + n) for n in range(5)]
    assert delivery_alerts(tickets, PARCELS, AT) == []


async def test_a_normal_day_raises_no_alerts(sim: Simulator) -> None:  # noqa: F811
    run = await sim.control.start("normal-day", seed=7, schedule=False)
    await sim.control.drive(run.run_id)
    assert EventKind.KPI_ALERT not in {event.kind for event in await sim.all_events()}


async def test_a_carrier_delay_is_caught_within_two_hours(sim: Simulator) -> None:  # noqa: F811
    run = await sim.control.start("carrier-delay", seed=7, schedule=False)
    await sim.control.drive(run.run_id)
    alerts = [KpiAlert.model_validate(e.payload) for e in await sim.all_events() if e.kind is EventKind.KPI_ALERT]
    assert alerts
    assert {tuple(alert.segment.values()) for alert in alerts} == {("northstar", "northeast")}
    began = run.started_at.astimezone(STORE_TIME).replace(hour=10, minute=0)
    assert began < alerts[0].detected_at <= began + timedelta(hours=2)


async def test_alerts_reach_the_team_only_when_the_run_asks(sim: Simulator) -> None:  # noqa: F811
    raised: list[tuple[str, str]] = []

    class Desk:
        async def raise_alert(self, alert: KpiAlert, today: date, *, scope: str, actor: str = "monitor") -> WorkItem:
            raised.append((alert.metric, scope))
            return None  # type: ignore[return-value]

    deps = replace(sim.deps, alerts=Desk())
    control = SimControl(deps, sim.control._baseline, queue=None)
    quiet = await control.start("carrier-delay", seed=7, schedule=False)
    await control.drive(quiet.run_id)
    assert raised == []
    loud = await control.start("carrier-delay", seed=7, alerts_to_agents=True, schedule=False)
    await control.drive(loud.run_id)
    assert raised
    assert {scope for _, scope in raised} == {loud.run_id}


async def test_the_delay_holds_deliveries_and_brings_customers(sim: Simulator) -> None:  # noqa: F811
    run = await sim.control.start("carrier-delay", seed=7, schedule=False)
    normal = await sim.control.start("normal-day", seed=7, schedule=False)
    delayed = await sim.deps.runs.due(run.run_id, after=run.started_at, until=run.ends_at)
    usual = await sim.deps.runs.due(normal.run_id, after=normal.started_at, until=normal.ends_at)
    stuck = {
        s.tracking_id
        for s in await sim.world.shipments()
        if s.status == "in_transit" and (s.carrier, s.region) == ("northstar", "northeast")
    }
    began = run.started_at.astimezone(STORE_TIME).replace(hour=10, minute=0)
    assert not [
        e
        for e in delayed
        if isinstance(e.effect, ParcelDelivered) and e.effect.tracking_id in stuck and e.due_at >= began
    ]
    usual_tickets = {e.effect.ticket_id for e in usual if isinstance(e.effect, TicketOpened)}
    extra = [
        e.effect for e in delayed if isinstance(e.effect, TicketOpened) and e.effect.ticket_id not in usual_tickets
    ]
    moments = [
        e.due_at for e in delayed if isinstance(e.effect, TicketOpened) and e.effect.ticket_id not in usual_tickets
    ]
    assert extra
    assert {ticket.brief.intent for ticket in extra} == {"where_is_my_order"}
    assert all(began < moment <= began + CARRIER_DELAY.delay.contact_within for moment in moments)  # type: ignore[union-attr]

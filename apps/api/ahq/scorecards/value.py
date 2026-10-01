from __future__ import annotations

import statistics
from collections.abc import Sequence

from ahq.domain import AgentRun, Incident, WorkItem, WorkStatus
from ahq.domain.world import Shipment, Ticket
from ahq.scorecards.types import TeamValue

WITH_PEOPLE = frozenset({WorkStatus.ESCALATED})
SETTLED = frozenset({WorkStatus.DONE, WorkStatus.ESCALATED})


def team_value(
    items: Sequence[WorkItem],
    runs: Sequence[AgentRun],
    incidents: Sequence[Incident],
    shipments: Sequence[Shipment],
    complaints: Sequence[Ticket],
    *,
    human_cost_per_ticket_usd: float,
) -> TeamValue:
    resolved = [item for item in items if item.status is WorkStatus.DONE]
    with_people = [item for item in items if item.status in WITH_PEOPLE]
    settled = len(resolved) + len(with_people)
    ticket_ids = {item.id for item in items}
    ticket_runs = [run for run in runs if run.work_item_id in ticket_ids]
    cost = round(sum(run.cost_usd for run in ticket_runs), 6)
    human = round(len(resolved) * human_cost_per_ticket_usd, 2)
    minutes = [(item.updated_at - item.created_at).total_seconds() / 60 for item in resolved]
    delayed, reached = _reached_first(incidents, shipments, complaints)
    return TeamValue(
        tickets=len(items),
        resolved=len(resolved),
        with_people=len(with_people),
        open=len(items) - settled,
        deflection_rate=len(resolved) / settled if settled else None,
        ticket_cost_usd=cost,
        cost_per_resolved_usd=round(cost / len(resolved), 6) if resolved else None,
        human_cost_per_ticket_usd=human_cost_per_ticket_usd,
        human_cost_usd=human,
        net_savings_usd=round(human - cost, 2),
        median_minutes_to_resolve=round(statistics.median(minutes), 1) if minutes else None,
        approvals_per_100=round(100 * sum(run.approvals for run in ticket_runs) / len(items), 1) if items else None,
        incidents=len(incidents),
        delayed_customers=delayed,
        reached_first=reached,
    )


def _reached_first(
    incidents: Sequence[Incident], shipments: Sequence[Shipment], complaints: Sequence[Ticket]
) -> tuple[int, int]:
    delayed = reached = 0
    for incident in incidents:
        affected = incident.report.affected
        if affected.carrier is None or affected.region is None:
            continue
        at = incident.detected_at
        held = {
            s.order_id
            for s in shipments
            if s.carrier == affected.carrier.lower()
            and s.region == affected.region.lower()
            and s.shipped_at is not None
            and s.shipped_at <= at
            and (s.delivered_at is None or s.delivered_at > at)
        }
        wrote = {t.order_id for t in complaints if t.order_id in held and t.created_at <= at}
        delayed += len(held)
        reached += len(held - wrote)
    return delayed, reached

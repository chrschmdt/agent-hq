from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta

from ahq.analytics import count_excess
from ahq.domain import KpiAlert
from ahq.domain.world import Shipment, Ticket

METRIC = "where_is_my_order_tickets"
WINDOW = timedelta(hours=3)
WATCHED_INTENT = "where_is_my_order"

type Segment = tuple[str, str]


def check_times(after: datetime, until: datetime) -> Iterator[datetime]:
    hour = after.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while hour <= until:
        yield hour
        hour += timedelta(hours=1)


def delivery_alerts(tickets: Sequence[Ticket], shipments: Sequence[Shipment], at: datetime) -> list[KpiAlert]:
    in_transit = Counter((s.carrier, s.region) for s in shipments if s.status == "in_transit")
    parcels = sum(in_transit.values())
    if not parcels:
        return []
    segment_of = {s.order_id: (s.carrier, s.region) for s in shipments if s.status == "in_transit"}
    asked = Counter(
        segment_of[t.order_id]
        for t in tickets
        if t.intent == WATCHED_INTENT and t.order_id in segment_of and at - WINDOW < t.created_at <= at
    )
    total = sum(asked.values())
    alerts: list[KpiAlert] = []
    for segment, observed in sorted(asked.items()):
        share = in_transit[segment] / parcels
        expected = (total - observed) * share / (1 - share) if share < 1 else float(total)
        anomaly = count_excess(observed, expected)
        if anomaly is None:
            continue
        alerts.append(
            KpiAlert(
                metric=METRIC,
                segment={"carrier": segment[0], "region": segment[1]},
                window_hours=int(WINDOW.total_seconds() // 3600),
                value=anomaly.value,
                baseline=anomaly.baseline,
                z_score=anomaly.z_score,
                ratio=anomaly.ratio,
                samples=total,
                detected_at=at,
            )
        )
    return alerts

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ahq.sim.seeded import rng

HOURLY_WEIGHTS = (
    0.3, 0.2, 0.15, 0.1, 0.1, 0.2, 0.5, 0.9, 1.2, 1.4, 1.5, 1.6,
    1.8, 1.7, 1.5, 1.4, 1.3, 1.3, 1.4, 1.5, 1.4, 1.1, 0.8, 0.5,
)  # fmt: skip


def arrival_times(count: int, start: datetime, end: datetime, *, timezone: str, seed: int) -> list[datetime]:
    zone = ZoneInfo(timezone)
    minutes = [start + timedelta(minutes=offset) for offset in range(1, int((end - start).total_seconds() // 60) + 1)]
    weights = [HOURLY_WEIGHTS[moment.astimezone(zone).hour] for moment in minutes]
    return sorted(rng(seed, "arrivals").choices(minutes, weights=weights, k=count))

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence

from ahq.domain import Event, StrictModel

EFFECT_EVENTS = frozenset({"ticket.opened", "order.shipped", "parcel.delivered"})


class RunReport(StrictModel):
    counts: dict[str, int]
    events_digest: str
    store_hash: str


def report_run(events: Sequence[Event], store_hash: str) -> RunReport:
    effects = [event for event in events if event.kind.value in EFFECT_EVENTS]
    encoded = json.dumps(
        [[event.kind.value, event.occurred_at.isoformat(), event.payload] for event in effects], sort_keys=True
    ).encode()
    return RunReport(
        counts=dict(sorted(Counter(event.kind.value for event in events).items())),
        events_digest=hashlib.sha256(encoded).hexdigest(),
        store_hash=store_hash,
    )

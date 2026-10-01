from __future__ import annotations

import hashlib

BUCKETS = 10_000


def position(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % BUCKETS


def bucket(work_item_id: str, agent: str, pct: int) -> bool:
    return position(f"{agent}:{work_item_id}") < pct * BUCKETS // 100


def in_share(key: str, share: float) -> bool:
    return position(key) < round(share * BUCKETS)

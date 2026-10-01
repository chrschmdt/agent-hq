from __future__ import annotations

import hashlib
import random


def rng(seed: int, *labels: object) -> random.Random:
    key = ":".join(str(part) for part in (seed, *labels))
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))

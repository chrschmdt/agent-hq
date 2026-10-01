from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from ahq.domain import ToolResult
from ahq.ports import Clock

TTL = timedelta(minutes=10)
SIZE = 2_000


class ReadCache:
    def __init__(self, clock: Clock, *, ttl: timedelta = TTL, size: int = SIZE) -> None:
        self._clock = clock
        self._ttl = ttl
        self._size = size
        self._entries: OrderedDict[str, tuple[datetime, ToolResult]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(tool: str, arguments: Mapping[str, Any], scope: Mapping[str, str]) -> str:
        canonical = json.dumps({"tool": tool, "arguments": arguments, "scope": scope}, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get(self, key: str) -> ToolResult | None:
        entry = self._entries.get(key)
        if entry is None or self._clock.now() - entry[0] > self._ttl:
            self._entries.pop(key, None)
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return entry[1]

    def put(self, key: str, result: ToolResult) -> None:
        if not result.ok:
            return
        self._entries[key] = (self._clock.now(), result)
        self._entries.move_to_end(key)
        while len(self._entries) > self._size:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

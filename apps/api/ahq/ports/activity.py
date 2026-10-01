from __future__ import annotations

from typing import Protocol


class ActivityStore(Protocol):
    async def clear(self, *, versions: bool) -> dict[str, int]: ...

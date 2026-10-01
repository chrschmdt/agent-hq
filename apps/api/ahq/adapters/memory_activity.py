from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from langgraph.checkpoint.memory import InMemorySaver


class HoldsActivity(Protocol):
    def clear_activity(self) -> dict[str, int]: ...


class MemoryCheckpoints:
    def __init__(self, saver: InMemorySaver) -> None:
        self._saver = saver

    def clear_activity(self) -> dict[str, int]:
        counts = {
            "public.checkpoint_writes": len(self._saver.writes),
            "public.checkpoint_blobs": len(self._saver.blobs),
            "public.checkpoints": sum(
                len(checkpoints) for thread in self._saver.storage.values() for checkpoints in thread.values()
            ),
        }
        for thread_id in list(self._saver.storage):
            self._saver.delete_thread(thread_id)
        return counts


class MemoryActivityStore:
    def __init__(self, holders: Sequence[HoldsActivity], *, versions: Callable[[], dict[str, int]]) -> None:
        self._holders = holders
        self._versions = versions

    async def clear(self, *, versions: bool) -> dict[str, int]:
        counts: dict[str, int] = {}
        for holder in self._holders:
            counts.update(holder.clear_activity())
        if versions:
            counts.update(self._versions())
        return counts

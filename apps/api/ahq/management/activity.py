from __future__ import annotations

from collections.abc import Callable

from ahq.domain import ActivityReport, ConflictError, EventKind, NewEvent
from ahq.management.versions import VersionRegistry
from ahq.ports import ActivityStore, Clock, EventLog, SimStore, WorkStore
from ahq.retrieval import KnowledgeBase


class ActivityDesk:
    def __init__(
        self,
        activity: ActivityStore,
        *,
        knowledge: KnowledgeBase,
        versions: VersionRegistry,
        work: WorkStore,
        runs: SimStore,
        events: EventLog,
        clock: Clock,
        after: Callable[[], None] | None = None,
    ) -> None:
        self._activity = activity
        self._knowledge = knowledge
        self._versions = versions
        self._work = work
        self._runs = runs
        self._events = events
        self._clock = clock
        self._after = after

    async def clear(self, *, versions: bool, by: str) -> ActivityReport:
        latest = await self._runs.latest()
        if latest is not None and latest.status == "running":
            raise ConflictError("a simulated day is running; stop it first")
        if await self._work.count_active():
            raise ConflictError("work is in flight; wait until it finishes")
        records = await self._activity.clear(versions=versions)
        passages = await self._knowledge.restore()
        report = ActivityReport(
            records=records, versions=versions, passages=passages, cleared_by=by, cleared_at=self._clock.now()
        )
        await self._events.append(
            [
                NewEvent(
                    kind=EventKind.ACTIVITY_CLEARED,
                    occurred_at=report.cleared_at,
                    actor=by,
                    payload={"versions": versions, "records": sum(records.values()), "passages": passages},
                )
            ]
        )
        if versions:
            await self._versions.sync()
        if self._after is not None:
            self._after()
        return report

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import JsonValue

from ahq.domain import (
    ConflictError,
    EventKind,
    KpiAlert,
    NewEvent,
    NotFoundError,
    PatternFlag,
    ProposalRecord,
    WorkItem,
    WorkItemId,
    WorkKind,
)
from ahq.ports import Clock, EventLog, TeamRecords
from ahq.retrieval import KbDocument, KnowledgeBase
from ahq.runtime.commands import Commands
from ahq.runtime.store_time import StoreTime

LIVE = "live"


def alert_key(alert: KpiAlert, today: date, scope: str = LIVE) -> str:
    segment = ",".join(f"{key}={value}" for key, value in sorted(alert.segment.items()))
    return f"alert:{scope}:{alert.metric}:{segment}:{today.isoformat()}"


def flag_key(flag: PatternFlag, today: date, scope: str = LIVE) -> str:
    return f"flag:{scope}:{flag.topic}:{today.isoformat()}"


@dataclass(frozen=True)
class TeamDesk:
    commands: Commands
    records: TeamRecords
    knowledge: KnowledgeBase
    events: EventLog
    clock: Clock
    start_flagged_work: bool = True
    on_publish: Callable[[], None] | None = None
    store_time: StoreTime | None = None

    async def publish_article(self, doc_id: str, version: int, day: date, *, actor: str = "scenario") -> bool:
        if not await self.knowledge.bring_forward(doc_id, version, day):
            return False
        if self.on_publish is not None:
            self.on_publish()
        payload: dict[str, JsonValue] = {"doc_id": doc_id, "version": version, "effective_date": day.isoformat()}
        await self._emit(EventKind.KB_PUBLISHED, None, actor, payload)
        return True

    async def raise_alert(self, alert: KpiAlert, today: date, *, scope: str = LIVE, actor: str = "monitor") -> WorkItem:
        work_input: dict[str, JsonValue] = {
            "alert": alert.model_dump(mode="json"),
            "today": today.isoformat(),
            "sim_run": scope,
        }
        key = alert_key(alert, today, scope)
        return await self.commands.submit_work(WorkKind.ALERT, work_input, actor=actor, key=key)

    async def raise_flag(self, source: str, flag: PatternFlag, today: date) -> str | None:
        work_item_id: str | None = None
        if self.start_flagged_work:
            scope = str((await self.commands.work.get(WorkItemId(source))).input.get("sim_run") or LIVE)
            work_input: dict[str, JsonValue] = {
                "flag": flag.model_dump(mode="json"),
                "today": today.isoformat(),
                "raised_at": (await self._now(source)).isoformat(),
                "flagged_by": "support",
                "source": source,
                "sim_run": scope,
            }
            key = flag_key(flag, today, scope)
            work_item_id = (await self.commands.submit_work(WorkKind.FLAG, work_input, actor="support", key=key)).id
        payload: dict[str, JsonValue] = {
            "topic": flag.topic,
            "summary": flag.summary,
            "ticket_ids": list(flag.ticket_ids),
            "source": source,
            "flag_work_item_id": work_item_id,
        }
        await self._emit(EventKind.PATTERN_FLAGGED, WorkItemId(source), "support", payload)
        return work_item_id

    async def _now(self, work_item_id: str) -> datetime:
        return await self.store_time.now(work_item_id) if self.store_time is not None else self.clock.now()

    async def decide_proposal(
        self, proposal_id: str, verdict: Literal["approved", "rejected"], *, actor: str, note: str | None = None
    ) -> ProposalRecord:
        pending = await self.records.proposal(proposal_id)
        if pending is None:
            raise NotFoundError(f"proposal {proposal_id} not found")
        if pending.status != "pending":
            raise ConflictError(f"proposal {proposal_id} is already {pending.status}")
        if pending.proposal.draft_id is not None:
            await self._settle_draft(pending, verdict, actor)
        record = await self.records.decide_proposal(proposal_id, verdict, by=actor, note=note, at=self.clock.now())
        payload: dict[str, JsonValue] = {"proposal_id": proposal_id, "verdict": verdict, "note": note}
        await self._emit(EventKind.PROPOSAL_DECIDED, WorkItemId(record.work_item_id), actor, payload)
        return record

    async def _settle_draft(self, record: ProposalRecord, verdict: Literal["approved", "rejected"], actor: str) -> None:
        draft_id = record.proposal.draft_id
        assert draft_id is not None
        draft = await self.records.draft(draft_id)
        if draft is None:
            raise NotFoundError(f"draft {draft_id} not found")
        if draft.status != "pending":
            raise ConflictError(f"draft {draft_id} is already {draft.status}")
        document = KbDocument.model_validate(draft.document)
        now = self.clock.now()
        if verdict == "rejected":
            await self.knowledge.discard(document)
            await self.records.set_draft_status(draft_id, "rejected", at=now)
            return
        await self.knowledge.publish(document, document.effective_date)
        if self.on_publish is not None:
            self.on_publish()
        await self.records.set_draft_status(draft_id, "published", at=now)
        payload: dict[str, JsonValue] = {
            "draft_id": draft_id,
            "doc_id": document.doc_id,
            "version": document.version,
            "effective_date": document.effective_date.isoformat(),
            "proposal_id": record.proposal_id,
        }
        await self._emit(EventKind.KB_PUBLISHED, WorkItemId(record.work_item_id), actor, payload)

    async def _emit(
        self, kind: EventKind, work_item_id: WorkItemId | None, actor: str, payload: dict[str, JsonValue]
    ) -> None:
        event = NewEvent(
            kind=kind, occurred_at=self.clock.now(), work_item_id=work_item_id, actor=actor, payload=payload
        )
        await self.events.append([event])

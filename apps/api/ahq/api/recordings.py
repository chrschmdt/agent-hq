from __future__ import annotations

import asyncio
import gzip
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import AwareDatetime, Field

from ahq.agents import SPECS
from ahq.api.routes.agents import AgentDetail, Lineup, LineupModel, get_agent
from ahq.api.routes.management import COMPLAINTS_BEFORE, AgentScorecards, scorecards
from ahq.api.routes.quality import GuardrailSummary, guardrail_summary
from ahq.api.routes.runs import RunApproval, load_run
from ahq.app.container import Container
from ahq.config import ModelRole, ProfileName, load_roi_config
from ahq.domain import (
    AgentRun,
    AgentVersion,
    Approval,
    ApprovalId,
    ConflictError,
    Event,
    EventKind,
    Incident,
    KbDraft,
    NotFoundError,
    ProposalRecord,
    ReviewRecord,
    StrictModel,
    WorkItem,
    WorkItemId,
    WorkKind,
    WorkStatus,
)
from ahq.domain.recordings import RecordingInfo, RecordingSummary, new_recording_id
from ahq.domain.retail import Order, User
from ahq.domain.sim import SimRun
from ahq.domain.world import KpiMetric, KpiPoint, Shipment, Ticket
from ahq.graphs import PathStep, ThreadView
from ahq.scorecards import TeamValue, team_value

RECORDING_VERSION = 2
PAGE = 5_000
MAX_BUNDLE_BYTES = 4_000_000
KPIS: tuple[KpiMetric, ...] = ("orders", "late_delivery_rate", "tickets", "csat")
LINEUP_ROLES: tuple[ModelRole, ...] = ("guard", "dispatcher", "support", "ops", "insights", "qa", "customer")
VALUE_EVERY_CALLS = 10
ORDER_ID = re.compile(r"#W\d{7}")
USER_ID = re.compile(r'user_id\\*"\s*:\s*\\*"([a-z][a-z0-9_]*)')
STATUS_EVENTS: dict[EventKind, WorkStatus] = {
    EventKind.WORK_CREATED: WorkStatus.NEW,
    EventKind.WORK_STARTED: WorkStatus.RUNNING,
    EventKind.WORK_WAITING_APPROVAL: WorkStatus.WAITING_APPROVAL,
    EventKind.WORK_WAITING_CUSTOMER: WorkStatus.WAITING_CUSTOMER,
    EventKind.WORK_COMPLETED: WorkStatus.DONE,
    EventKind.WORK_ESCALATED: WorkStatus.ESCALATED,
    EventKind.WORK_FAILED: WorkStatus.FAILED,
    EventKind.WORK_CANCELLED: WorkStatus.CANCELLED,
}


class WorkChange(StrictModel):
    at: int
    status: WorkStatus
    owner: str | None
    updated_at: AwareDatetime


class RecordedWork(StrictModel):
    at: int
    changes: list[WorkChange]
    item: WorkItem


class RecordedApproval(StrictModel):
    at: int
    settled_at: int | None
    pending: Approval
    record: Approval


class RecordedProposal(StrictModel):
    at: int
    settled_at: int | None
    pending: ProposalRecord
    record: ProposalRecord


class RecordedDraft(StrictModel):
    at: int
    settled_at: int | None
    pending: KbDraft
    record: KbDraft


class RecordedIncident(StrictModel):
    at: int
    record: Incident


class RecordedReview(StrictModel):
    at: int
    record: ReviewRecord


class RecordedRun(StrictModel):
    item: WorkItem
    path: list[PathStep]
    approvals: list[RunApproval]
    ticket: Ticket | None
    incident: Incident | None
    proposals: list[ProposalRecord]
    agent_runs: list[AgentRun]
    reviews: list[ReviewRecord]
    thread: ThreadView | None
    message_at: dict[str, list[int]] = Field(description="Per channel, the event each message appeared at, in order.")


class ValuePoint(StrictModel):
    at: int
    value: TeamValue


class GuardrailPoint(StrictModel):
    at: int
    summary: GuardrailSummary


class RecordedAgent(StrictModel):
    detail: AgentDetail
    versions: list[AgentVersion]
    scorecards: AgentScorecards


class RecordedStore(StrictModel):
    tickets: list[Ticket] = Field(default_factory=list)
    orders: list[Order] = Field(default_factory=list)
    customers: list[User] = Field(default_factory=list)
    shipments: list[Shipment] = Field(default_factory=list)


class Recording(StrictModel):
    version: int = RECORDING_VERSION
    id: str
    title: str
    recorded_at: AwareDatetime
    profile: str
    lineup: Lineup
    sim_run: SimRun
    events: list[Event]
    work: list[RecordedWork]
    approvals: list[RecordedApproval]
    incidents: list[RecordedIncident]
    proposals: list[RecordedProposal]
    drafts: list[RecordedDraft]
    reviews: list[RecordedReview]
    runs: dict[str, RecordedRun]
    value: list[ValuePoint]
    guardrails: list[GuardrailPoint]
    kpis: dict[str, list[KpiPoint]]
    agents: list[RecordedAgent]
    store: RecordedStore = Field(default_factory=RecordedStore)


async def record_day(container: Container, sim_run_id: str, *, title: str | None, by: str) -> RecordingInfo:
    run = await container.sim_runs.get(sim_run_id)
    if run is None:
        raise NotFoundError(f"simulated day {sim_run_id} not found")
    if run.status in ("running", "paused"):
        raise ConflictError(f"simulated day {sim_run_id} is still {run.status}")
    recording = await build_recording(
        container, run, recording_id=new_recording_id(), title=title or default_title(run)
    )
    bundle = gzip.compress(recording.model_dump_json().encode(), compresslevel=9, mtime=0)
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ConflictError(
            f"the recorded day takes {len(bundle) / 1e6:.1f} MB compressed, over the 4 MB the api serves"
        )
    info = RecordingInfo(
        id=recording.id,
        sim_run_id=run.run_id,
        title=recording.title,
        published=True,
        summary=summarize(recording),
        size_bytes=len(bundle),
        created_by=by,
        created_at=recording.recorded_at,
    )
    return await container.recordings.add(info, bundle)


async def publish_file(container: Container, path: Path, *, by: str) -> RecordingInfo:
    bundle = await asyncio.to_thread(path.read_bytes)
    recording = Recording.model_validate_json(gzip.decompress(bundle))
    info = RecordingInfo(
        id=recording.id,
        sim_run_id=recording.sim_run.run_id,
        title=recording.title,
        published=True,
        summary=summarize(recording),
        size_bytes=len(bundle),
        created_by=by,
        created_at=recording.recorded_at,
    )
    return await container.recordings.add(info, bundle)


def default_title(run: SimRun) -> str:
    scenario = run.scenario.replace("-", " ").capitalize()
    return f"{scenario}, {run.started_at:%B} {run.started_at.day}"


def summarize(recording: Recording) -> RecordingSummary:
    kinds = Counter(event.kind for event in recording.events)
    cost = sum(
        float(value)
        for event in recording.events
        if event.kind in (EventKind.MODEL_CALLED, EventKind.QA_REVIEWED)
        and isinstance(value := event.payload.get("cost_usd"), int | float)
    )
    return RecordingSummary(
        scenario=recording.sim_run.scenario,
        seed=recording.sim_run.seed,
        profile=recording.profile,
        sim_started_at=recording.sim_run.started_at,
        sim_ended_at=recording.sim_run.sim_now,
        events=len(recording.events),
        tickets=kinds[EventKind.TICKET_OPENED],
        agent_tickets=sum(1 for work in recording.work if work.item.kind is WorkKind.TICKET),
        model_calls=kinds[EventKind.MODEL_CALLED],
        tool_calls=kinds[EventKind.TOOL_CALLED],
        approvals=kinds[EventKind.APPROVAL_REQUESTED],
        incidents=kinds[EventKind.INCIDENT_FILED],
        cost_usd=round(cost, 4),
    )


async def build_recording(container: Container, run: SimRun, *, recording_id: str, title: str) -> Recording:
    events = day_events(await _all_events(container), run.run_id)
    by_item: dict[str, list[Event]] = {}
    for event in events:
        if event.work_item_id is not None:
            by_item.setdefault(str(event.work_item_id), []).append(event)

    work: list[RecordedWork] = []
    runs: dict[str, RecordedRun] = {}
    for work_item_id, item_events in by_item.items():
        view = await load_run(container, WorkItemId(work_item_id))
        thread = await container.threads.view(work_item_id)
        work.append(RecordedWork(at=item_events[0].id, changes=work_changes(view.item, item_events), item=view.item))
        runs[work_item_id] = RecordedRun(
            item=view.item,
            path=view.path,
            approvals=view.approvals,
            ticket=view.ticket,
            incident=view.incident,
            proposals=view.proposals,
            agent_runs=view.agent_runs,
            reviews=view.reviews,
            thread=thread,
            message_at=message_times(thread, item_events),
        )

    incidents = [
        RecordedIncident(at=event.id, record=found)
        for event in _of(events, EventKind.INCIDENT_FILED)
        if (found := await container.records.incident(str(event.payload.get("incident_id")))) is not None
    ]
    proposals = await _proposals(container, events)
    profile, lineup = day_lineup(container, events)
    recording = Recording(
        id=recording_id,
        title=title,
        recorded_at=container.clock.now(),
        profile=profile,
        lineup=lineup,
        sim_run=run,
        events=events,
        work=work,
        approvals=await _approvals(container, events),
        incidents=incidents,
        proposals=proposals,
        drafts=await _drafts(container, events, proposals),
        reviews=await _reviews(container, events),
        runs=runs,
        value=await _value(container, events, work, runs, incidents),
        guardrails=guardrail_points(events),
        kpis={metric: await container.world.kpis(metric, "store", days=30) for metric in KPIS},
        agents=await _agents(container),
    )
    return recording.model_copy(update={"store": await _store(container, recording)})


async def _store(container: Container, recording: Recording) -> RecordedStore:
    ticket_ids = sorted({str(event.payload["ticket_id"]) for event in _of(recording.events, EventKind.TICKET_OPENED)})
    tickets = [ticket for ticket_id in ticket_ids if (ticket := await container.world.ticket(ticket_id)) is not None]
    named = recording.model_dump_json() + "".join(ticket.model_dump_json() for ticket in tickets)
    store = await container.retail.snapshot()
    order_ids = sorted(set(ORDER_ID.findall(named)) & store.orders.keys())
    orders = [store.orders[order_id] for order_id in order_ids]
    user_ids = sorted(
        (
            set(USER_ID.findall(named))
            | {order.user_id for order in orders}
            | {ticket.user_id for ticket in tickets if ticket.user_id}
        )
        & store.users.keys()
    )
    customers = [store.users[user_id] for user_id in user_ids]
    shipments = [shipment for shipment in await container.world.shipments() if shipment.order_id in set(order_ids)]
    return RecordedStore(tickets=tickets, orders=orders, customers=customers, shipments=shipments)


def day_events(events: list[Event], run_id: str) -> list[Event]:
    starts = [i for i, e in enumerate(events) if e.kind is EventKind.SIM_STARTED]
    first = next((i for i in starts if events[i].payload.get("run_id") == run_id), None)
    if first is None:
        raise NotFoundError(f"no start of simulated day {run_id} in the event log")
    following = next((i for i in starts if i > first), len(events))
    return events[first:following]


def guardrail_points(events: Sequence[Event]) -> list[GuardrailPoint]:
    blocked = _of(events, EventKind.GUARDRAIL_BLOCKED)
    return [
        GuardrailPoint(at=event.id, summary=guardrail_summary(list(reversed(blocked[: index + 1]))))
        for index, event in enumerate(blocked)
    ]


def work_changes(item: WorkItem, events: Sequence[Event]) -> list[WorkChange]:
    changes: list[WorkChange] = []
    status: WorkStatus | None = None
    owner = item.input.get("owner") if isinstance(item.input.get("owner"), str) else None
    for event in events:
        next_status = STATUS_EVENTS.get(event.kind, status)
        next_owner = owner
        if event.kind is EventKind.WORK_ROUTED and isinstance(route := event.payload.get("route"), str):
            next_owner = route
        elif event.kind is EventKind.AGENT_HANDOFF and isinstance(target := event.payload.get("to"), str):
            next_owner = target
        if next_status is not None and (next_status, next_owner) != (status, owner):
            status, owner = next_status, str(next_owner) if next_owner is not None else None
            changes.append(WorkChange(at=event.id, status=status, owner=owner, updated_at=event.occurred_at))
    if not changes or (changes[-1].status, changes[-1].owner) != (item.status, item.owner):
        last = events[-1] if events else None
        changes.append(
            WorkChange(
                at=last.id if last else 0,
                status=item.status,
                owner=item.owner,
                updated_at=item.updated_at,
            )
        )
    return changes


def message_times(thread: ThreadView | None, events: Sequence[Event]) -> dict[str, list[int]]:
    if thread is None or not events:
        return {}
    produced = {
        str(e.payload["message_id"]): e.id for e in _of(events, EventKind.MODEL_CALLED) if "message_id" in e.payload
    }
    answered = {str(e.payload["call_id"]): e.id for e in _of(events, EventKind.TOOL_CALLED) if "call_id" in e.payload}
    said = [(e.id, e.payload.get("body")) for e in _of(events, EventKind.TICKET_MESSAGE)]
    times: dict[str, list[int]] = {}
    for channel, messages in thread.channels.items():
        known: list[int | None] = []
        for message in messages:
            at: int | None = None
            if message.id is not None and message.id in produced:
                at = produced[message.id]
            elif message.tool_call_id is not None and message.tool_call_id in answered:
                at = answered[message.tool_call_id]
            elif message.kind == "human":
                at = next((event_id for event_id, body in said if body == message.text), None)
            known.append(at)
        times[channel] = _fill(known, default=events[0].id)
    return times


def day_lineup(container: Container, events: Sequence[Event]) -> tuple[ProfileName, Lineup]:
    catalog = container.catalog
    seen: dict[str, Counter[str]] = {}
    for event in events:
        role = (
            event.actor
            if event.kind is EventKind.MODEL_CALLED
            else "qa"
            if event.kind is EventKind.QA_REVIEWED
            else None
        )
        model = event.payload.get("model")
        if role is not None and isinstance(model, str) and model in catalog.models:
            seen.setdefault(role, Counter())[model] += 1
    played = {role: counts.most_common(1)[0][0] for role, counts in seen.items()}

    def matches(profile: ProfileName) -> int:
        return sum(1 for role, key in played.items() if catalog.profiles[profile].get(role) == key)  # pyright: ignore[reportArgumentType]

    current = container.model_switch.current
    profile = max(catalog.profiles, key=lambda name: (matches(name), name == current)) if played else current
    roles: dict[str, LineupModel] = {}
    for role in LINEUP_ROLES:
        key = played.get(role) or catalog.resolve(profile, role)[0]
        spec = catalog.models[key]
        provider = spec.id.split("/", 1)[0] if "/" in spec.id else spec.route
        roles[role] = LineupModel(key=key, id=spec.id, provider=provider, reasoning=spec.reasoning is not None)
    return profile, Lineup(profile=profile, roles=roles, embeddings=catalog.embeddings.id, rerank=catalog.rerank.id)


def _fill(known: Sequence[int | None], *, default: int) -> list[int]:
    filled: list[int] = []
    for index, at in enumerate(known):
        later = next((value for value in known[index + 1 :] if value is not None), None)
        fallback = later if later is not None else (filled[-1] if filled else default)
        filled.append(at if at is not None else fallback)
    return filled


def _of(events: Sequence[Event], kind: EventKind) -> list[Event]:
    return [event for event in events if event.kind is kind]


def _settled(events: Sequence[Event], kind: EventKind, key: str, value: str) -> int | None:
    return next((e.id for e in events if e.kind is kind and e.payload.get(key) == value), None)


async def _approvals(container: Container, events: Sequence[Event]) -> list[RecordedApproval]:
    recorded: list[RecordedApproval] = []
    for event in _of(events, EventKind.APPROVAL_REQUESTED):
        approval_id = str(event.payload.get("approval_id"))
        try:
            record = await container.approvals.get(ApprovalId(approval_id))
        except NotFoundError:
            continue
        recorded.append(
            RecordedApproval(
                at=event.id,
                settled_at=_settled(events, EventKind.APPROVAL_DECIDED, "approval_id", approval_id),
                pending=record.model_copy(
                    update={"status": "pending", "decision": None, "decided_by": None, "decided_at": None}
                ),
                record=record,
            )
        )
    return recorded


async def _proposals(container: Container, events: Sequence[Event]) -> list[RecordedProposal]:
    recorded: list[RecordedProposal] = []
    for event in _of(events, EventKind.PROPOSAL_CREATED):
        proposal_id = str(event.payload.get("proposal_id"))
        record = await container.records.proposal(proposal_id)
        if record is None:
            continue
        recorded.append(
            RecordedProposal(
                at=event.id,
                settled_at=_settled(events, EventKind.PROPOSAL_DECIDED, "proposal_id", proposal_id),
                pending=record.model_copy(
                    update={"status": "pending", "decided_by": None, "note": None, "decided_at": None}
                ),
                record=record,
            )
        )
    return recorded


async def _drafts(
    container: Container, events: Sequence[Event], proposals: Sequence[RecordedProposal]
) -> list[RecordedDraft]:
    recorded: list[RecordedDraft] = []
    for proposal in proposals:
        draft_id = proposal.record.proposal.draft_id
        if draft_id is None or (record := await container.records.draft(draft_id)) is None:
            continue
        published = _settled(events, EventKind.KB_PUBLISHED, "draft_id", draft_id)
        recorded.append(
            RecordedDraft(
                at=proposal.at,
                settled_at=published if published is not None else proposal.settled_at,
                pending=record.model_copy(update={"status": "pending", "published_at": None}),
                record=record,
            )
        )
    return recorded


async def _reviews(container: Container, events: Sequence[Event]) -> list[RecordedReview]:
    recorded: list[RecordedReview] = []
    for event in _of(events, EventKind.QA_REVIEWED):
        agent = event.payload.get("agent")
        if event.work_item_id is None or not isinstance(agent, str):
            continue
        review = await container.quality.store.review(str(event.work_item_id), agent)
        if review is not None:
            recorded.append(RecordedReview(at=event.id, record=review))
    return recorded


async def _agents(container: Container) -> list[RecordedAgent]:
    agents: list[RecordedAgent] = []
    for name in SPECS:
        detail = await get_agent(name, container)
        agents.append(
            RecordedAgent(
                detail=detail.model_copy(update={"recent_events": [], "recent_work": []}),
                versions=await container.versions.store.list(name),
                scorecards=await scorecards(name, container),
            )
        )
    return agents


async def _value(
    container: Container,
    events: Sequence[Event],
    work: Sequence[RecordedWork],
    runs: dict[str, RecordedRun],
    incidents: Sequence[RecordedIncident],
) -> list[ValuePoint]:
    tickets = [recorded for recorded in work if recorded.item.kind is WorkKind.TICKET]
    ticket_ids = {recorded.item.id for recorded in tickets}
    moments = {change.at for recorded in tickets for change in recorded.changes}
    moments |= {incident.at for incident in incidents}
    calls = [e for e in _of(events, EventKind.MODEL_CALLED) if e.work_item_id in ticket_ids]
    moments |= {event.id for event in calls[VALUE_EVERY_CALLS - 1 :: VALUE_EVERY_CALLS]}
    if not moments:
        return []
    filed = [incident.record for incident in incidents]
    complaints: list[Ticket] = []
    if filed:
        first = min(incident.detected_at for incident in filed)
        last = max(incident.detected_at for incident in filed)
        complaints = await container.world.tickets_opened(first - COMPLAINTS_BEFORE, last)
    shipments = await container.world.shipments() if filed else []
    human_cost = load_roi_config().human_cost_per_ticket_usd
    spent: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for event in calls:
        cost = event.payload.get("cost_usd")
        if isinstance(cost, int | float):
            spent.setdefault((str(event.work_item_id), str(event.actor)), []).append((event.id, float(cost)))
    requested: dict[str, list[int]] = {}
    for event in _of(events, EventKind.APPROVAL_REQUESTED):
        requested.setdefault(str(event.work_item_id), []).append(event.id)

    points: list[ValuePoint] = []
    for moment in sorted(moments):
        items = [_item_at(recorded, moment) for recorded in tickets if recorded.at <= moment]
        agent_runs = [
            _run_at(agent_run, moment, spent.get((agent_run.work_item_id, agent_run.agent), []), requested)
            for item in items
            for agent_run in runs[item.id].agent_runs
        ]
        value = team_value(
            items,
            agent_runs,
            [incident.record for incident in incidents if incident.at <= moment],
            shipments,
            complaints,
            human_cost_per_ticket_usd=human_cost,
        )
        if not points or points[-1].value != value:
            points.append(ValuePoint(at=moment, value=value))
    return points


def _item_at(recorded: RecordedWork, moment: int) -> WorkItem:
    change = next((c for c in reversed(recorded.changes) if c.at <= moment), recorded.changes[0])
    return recorded.item.model_copy(
        update={"status": change.status, "owner": change.owner, "updated_at": change.updated_at}
    )


def _run_at(
    run: AgentRun, moment: int, calls: Sequence[tuple[int, float]], requested: dict[str, list[int]]
) -> AgentRun:
    total = sum(cost for _, cost in calls)
    so_far = sum(cost for at, cost in calls if at <= moment)
    cost = run.cost_usd * so_far / total if total > 0 else run.cost_usd
    approvals = min(run.approvals, sum(1 for at in requested.get(run.work_item_id, []) if at <= moment))
    return run.model_copy(update={"cost_usd": cost, "approvals": approvals})


async def _all_events(container: Container) -> list[Event]:
    events: list[Event] = []
    while page := await container.events.read_after(events[-1].id if events else 0, limit=PAGE):
        events.extend(page)
    return events

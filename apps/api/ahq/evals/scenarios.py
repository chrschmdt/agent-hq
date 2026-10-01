from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ahq.adapters.clock import WallClock
from ahq.adapters.memory_management import MemorySlots
from ahq.agents import AgentSpec
from ahq.app.container import Container, Overrides, open_container
from ahq.config import load_budget_config, load_world_config
from ahq.domain import (
    ConfigurationError,
    ConflictError,
    Effect,
    Event,
    EventKind,
    Incident,
    NotFoundError,
    ProposalRecord,
    StrictModel,
    VersionStatus,
    WorkItem,
    WorkItemId,
    WorkKind,
)
from ahq.domain.retail import RetailSnapshot
from ahq.grading import (
    Conversation,
    ExpectationResult,
    attacks_contained,
    attacks_logged,
    every_customer_answered,
    incident_filed,
    new_version_cited,
    no_money_back,
    product_proposed,
    proposal_made,
    replies_cite_policy,
    rolled_back,
    within_budget,
    within_slots,
)
from ahq.ports import ChatModels
from ahq.settings import Settings
from ahq.sim.briefs import DEFECTIVE_PRODUCT
from ahq.sim.scenarios import SCENARIOS, CarrierDelay, Scenario
from ahq.tools import CATALOG

DETECT_WITHIN = timedelta(hours=2)
ROLLBACK_WITHIN = 10
MAX_DELIVERIES = 200_000
WRITE_TOOLS = frozenset(name for name, spec in CATALOG.items() if spec.effect is Effect.WRITE)
SURGE_CONCURRENCY = 16


class ScenarioTrial(StrictModel):
    seed: int
    passed: bool
    expectations: list[ExpectationResult]
    alerts: int
    work_items: int
    incidents: list[str]
    proposals: list[str]
    cost_usd: float
    seconds: float
    error: str | None = None


class ScenarioReport(StrictModel):
    scenario: str
    profile: str
    started_at: datetime
    trials: list[ScenarioTrial]
    cost_usd: float
    stopped_at_cap: bool

    @property
    def pass_rate(self) -> float:
        return sum(trial.passed for trial in self.trials) / len(self.trials) if self.trials else 0.0


async def check_scenario(
    settings: Settings,
    name: str,
    *,
    seed: int,
    trials: int,
    max_usd: float,
    versions: Mapping[str, AgentSpec] | None = None,
    models: ChatModels | None = None,
    progress: Callable[[ScenarioTrial], None] | None = None,
) -> ScenarioReport:
    scenario = SCENARIOS.get(name)
    if scenario is None:
        raise NotFoundError(f"unknown scenario {name!r}")
    if scenario.delay is None and scenario.deploy is None and not scenario.waves:
        raise ConfigurationError(f"scenario {name!r} has no expectations to check")
    if scenario.delay is not None and settings.database_url is None:
        raise ConfigurationError("this scenario needs DATABASE_URL: the analytics tools query Postgres")
    run_settings = settings.model_copy(
        update={"queue_backend": "inprocess", "tool_transport": "direct", "seed_memory": True}
    )
    started_at = WallClock().now()
    results: list[ScenarioTrial] = []
    spent = 0.0
    for trial_seed in range(seed, seed + trials):
        if spent >= max_usd:
            break
        result = await _trial(run_settings, scenario, trial_seed, Overrides(versions=versions, models=models))
        spent += result.cost_usd
        results.append(result)
        if progress is not None:
            progress(result)
    return ScenarioReport(
        scenario=name,
        profile=settings.model_profile,
        started_at=started_at,
        trials=results,
        cost_usd=round(spent, 6),
        stopped_at_cap=len(results) < trials,
    )


async def _trial(settings: Settings, scenario: Scenario, seed: int, overrides: Overrides) -> ScenarioTrial:
    clock = WallClock()
    began = clock.now()
    async with open_container(settings, overrides=overrides) as container:
        queue = container.inprocess_queue
        assert queue is not None
        cursor = await container.events.last_id()
        error: str | None = None
        started_at: datetime | None = None
        before = await container.retail.snapshot()
        try:
            run = await container.sim.start(
                scenario.name,
                seed=seed,
                agent_tickets=scenario.agent_tickets,
                alerts_to_agents=scenario.delay is not None,
            )
            started_at = run.started_at
            before = await container.retail.snapshot()
            concurrency = SURGE_CONCURRENCY if scenario.has_wave("mix") else 1
            await queue.run_until_idle(virtual_time=True, max_deliveries=MAX_DELIVERIES, concurrency=concurrency)
        except Exception as failure:  # a failed trial is a result, not the end of the check
            error = f"{type(failure).__name__}: {failure}"
        events = await container.events.read_after(cursor, limit=1_000_000)
        created = {str(e.work_item_id) for e in events if e.kind is EventKind.WORK_CREATED and e.work_item_id}
        incidents = [i for i in await container.records.incidents(500) if i.work_item_id in created]
        proposals = [p for p in await container.records.proposals() if p.work_item_id in created]
        expectations: list[ExpectationResult] = []
        if scenario.delay is not None:
            expectations += _delay_expectations(scenario.delay, started_at, incidents, proposals)
        if scenario.deploy is not None:
            expectations += await _deploy_expectations(container, events)
        if scenario.waves:
            items = [await container.work.get(WorkItemId(item_id)) for item_id in sorted(created)]
            expectations += await _wave_expectations(
                container, scenario, events, items, before, proposals, dead_letters=len(queue.dead_letters)
            )
    return ScenarioTrial(
        seed=seed,
        passed=error is None and all(expectation.met for expectation in expectations),
        expectations=expectations,
        alerts=sum(event.kind is EventKind.KPI_ALERT for event in events),
        work_items=len(created),
        incidents=[incident.incident_id for incident in incidents],
        proposals=[proposal.proposal_id for proposal in proposals],
        cost_usd=round(_spend(events), 6),
        seconds=round((clock.now() - began).total_seconds(), 1),
        error=error,
    )


def _delay_expectations(
    delay: CarrierDelay, started_at: datetime | None, incidents: list[Incident], proposals: list[ProposalRecord]
) -> list[ExpectationResult]:
    never = datetime.max.replace(tzinfo=ZoneInfo("UTC"))
    begins = _delay_start(started_at, delay) if started_at is not None else never
    return [
        incident_filed(incidents, carrier=delay.carrier, region=delay.region, by=begins + DETECT_WITHIN),
        proposal_made(proposals, {incident.incident_id for incident in incidents}),
    ]


async def _deploy_expectations(container: Container, events: list[Event]) -> list[ExpectationResult]:
    shipped = [e for e in events if e.kind is EventKind.VERSION_CANARY_STARTED and e.actor == "scenario"]
    if not shipped:
        return [ExpectationResult(name="bad change shipped as a canary", met=False, detail="it never shipped")]
    version_id = str(shipped[-1].payload["version_id"])
    runs = await container.ledger.runs(version_id=version_id, limit=10_000)
    result = rolled_back(events, runs, version_id, within=ROLLBACK_WITHIN)
    version = await container.versions.store.get(version_id)
    if version is not None and version.status is VersionStatus.CANARY:
        with contextlib.suppress(ConflictError):
            await container.versions.roll_back(version_id, by="scenario", reasons=["the scenario ended"])
    return [result]


async def _wave_expectations(
    container: Container,
    scenario: Scenario,
    events: list[Event],
    items: list[WorkItem],
    before: RetailSnapshot,
    proposals: list[ProposalRecord],
    *,
    dead_letters: int,
) -> list[ExpectationResult]:
    tickets = [item for item in items if item.kind is WorkKind.TICKET]
    deferred = sum(event.kind is EventKind.WORK_DEFERRED for event in events)
    results = [every_customer_answered(tickets, dead_letters=dead_letters, deferred=deferred)]
    if scenario.has_wave("mix"):
        budgets = load_budget_config()
        if isinstance(container.slots, MemorySlots):
            limits = {provider: budgets.calls.slots_for(provider) for provider in container.slots.peaks}
            results.append(within_slots(container.slots.peaks, limits))
        results.append(within_budget(_spend(events), budgets.daily.total_usd))
    talks = await _conversations(container, tickets, events)
    if scenario.has_wave("attack"):
        attacks = talks.get("attack", [])
        results.append(attacks_contained(attacks, events, WRITE_TOOLS, before))
        results.append(attacks_logged(attacks, events))
    if scenario.has_wave("refund_pressure"):
        pressed = talks.get("refund_pressure", [])
        results.append(no_money_back(pressed, before, await container.retail.snapshot()))
        results.append(replies_cite_policy(pressed))
    if scenario.has_wave("defect"):
        results.append(product_proposed(proposals, DEFECTIVE_PRODUCT, events))
    if scenario.has_wave("return_question") and scenario.upload is not None:
        asked = talks.get("return_question", [])
        results.append(new_version_cited(asked, scenario.upload.doc_id, scenario.upload.version))
    return results


async def _conversations(
    container: Container, tickets: list[WorkItem], events: list[Event]
) -> dict[str, list[Conversation]]:
    cited: dict[str, list[str]] = {}
    for event in events:
        if event.kind is EventKind.TICKET_REPLIED and event.work_item_id is not None:
            raw = event.payload.get("citations")
            if isinstance(raw, list):
                cited.setdefault(str(event.work_item_id), []).extend(str(c) for c in raw)
    found: dict[str, list[Conversation]] = {}
    for item in tickets:
        ticket = await container.tickets.ticket(str(item.input.get("ticket_id")))
        if ticket is None or ticket.user_id is None:
            continue
        found.setdefault(ticket.intent, []).append(
            Conversation(
                work_item_id=str(item.id),
                customer_id=ticket.user_id,
                order_id=ticket.order_id,
                wrote="\n".join(m.body for m in ticket.messages if m.author == "customer"),
                replies=[m.body for m in ticket.messages if m.author == "agent"],
                citations=cited.get(str(item.id), []),
            )
        )
    return found


def _delay_start(day_start: datetime, delay: CarrierDelay) -> datetime:
    local = day_start.astimezone(ZoneInfo(load_world_config().clock.timezone))
    return local.replace(hour=delay.starts.hour, minute=delay.starts.minute, second=0, microsecond=0)


def _spend(events: list[Event]) -> float:
    return sum(
        float(event.payload.get("cost_usd") or 0.0)  # pyright: ignore[reportArgumentType]
        for event in events
        if event.kind is EventKind.MODEL_CALLED
    )

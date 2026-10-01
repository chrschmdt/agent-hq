from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from ahq.adapters.clock import WallClock
from ahq.adapters.embedding_cache import CachingEmbedder
from ahq.agents import AgentSpec
from ahq.app.container import Container, Overrides, open_container, open_embedder
from ahq.config import ProfileName, load_model_catalog, load_world_config
from ahq.domain import ApprovalDecision, CustomerTurnJob, Event, EventKind, StrictModel, WorkStatus
from ahq.domain.retail import RetailSnapshot
from ahq.domain.world import TicketMessage
from ahq.grading import AssertionVerdict, Split, Tau3Task, gold_hash, judge_assertions, pass_hat_k, reward
from ahq.retail import STORE_TOOL_NAMES, canonical_hash
from ahq.settings import Settings
from ahq.sim.customer import GREETING, scenario

PATCHED_TASKS = frozenset({"20", "21", "37", "36", "100"})
NOT_IN_TAU3 = frozenset(STORE_TOOL_NAMES)


class TrialResult(StrictModel):
    task_id: str
    trial: int
    reward: float
    db_match: bool
    assertions: list[AssertionVerdict]
    outcome: str
    approvals: int
    customer_turns: int
    cost_usd: float
    seconds: float
    input_tokens: int = 0
    cached_tokens: int = Field(default=0, description="Input tokens the agents read from a prompt cache.")
    error: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
    transcript: list[str] = Field(default_factory=list)


class Tau3Report(StrictModel):
    profile: ProfileName
    split: Split
    task_ids: list[str]
    trials: int
    started_at: datetime
    results: list[TrialResult]
    pass_k: dict[int, float] = Field(default_factory=dict)
    cost_usd: float
    stopped_at_cap: bool
    patched_tasks: list[str]


async def run_tau3(
    settings: Settings,
    tasks: Sequence[Tau3Task],
    store: RetailSnapshot,
    *,
    split: Split,
    trials: int,
    max_usd: float,
    concurrency: int = 1,
    versions: Mapping[str, AgentSpec] | None = None,
    progress: Callable[[TrialResult], None] | None = None,
) -> Tau3Report:
    started = WallClock().now()
    run_settings = settings.model_copy(
        update={"queue_backend": "inprocess", "tool_transport": "direct", "qdrant_url": None, "database_url": None}
    )
    golds = {task.task_id: await gold_hash(task, store) for task in tasks}
    results: list[TrialResult] = []
    spent = 0.0
    capped = False
    gate = asyncio.Semaphore(concurrency)

    async with AsyncExitStack() as stack:
        embedder = await stack.enter_async_context(open_embedder(run_settings, load_model_catalog()))
        if run_settings.model_profile != "mock":
            cache = CachingEmbedder(
                embedder,
                run_settings.data_dir / "cache" / "embeddings.sqlite",
                model=load_model_catalog().embeddings.id,
            )
            stack.callback(cache.close)
            embedder = cache

        async def attempt(task: Tau3Task, trial: int) -> None:
            nonlocal spent, capped
            async with gate:
                if spent >= max_usd:
                    capped = True
                    return
                overrides = Overrides(
                    storage="memory",
                    store=store,
                    embedder=embedder,
                    flags_start_work=False,
                    review_runs=False,
                    versions=versions,
                )
                result = await run_trial(run_settings, overrides, task, trial, golds[task.task_id])
                spent += result.cost_usd
                results.append(result)
                if progress is not None:
                    progress(result)

        await asyncio.gather(*(attempt(task, trial) for trial in range(trials) for task in tasks))

    outcomes = {task.task_id: [r.reward == 1.0 for r in results if r.task_id == task.task_id] for task in tasks}
    complete = {task_id: runs for task_id, runs in outcomes.items() if len(runs) == trials}
    return Tau3Report(
        profile=run_settings.model_profile,
        split=split,
        task_ids=[task.task_id for task in tasks],
        trials=trials,
        started_at=started,
        results=sorted(results, key=lambda r: (int(r.task_id), r.trial)),
        pass_k={k: pass_hat_k(complete, k) for k in range(1, trials + 1)} if complete else {},
        cost_usd=round(spent, 6),
        stopped_at_cap=capped,
        patched_tasks=sorted(PATCHED_TASKS & {task.task_id for task in tasks}, key=int),
    )


async def run_trial(settings: Settings, overrides: Overrides, task: Tau3Task, trial: int, gold: str) -> TrialResult:
    clock = WallClock()
    began = clock.now()
    async with open_container(settings, overrides=overrides) as container:
        try:
            outcome, approvals = await _converse(container, task)
            error = None
        except Exception as failure:  # a failed trial is a result, not the end of the run
            outcome, approvals, error = "error", 0, f"{type(failure).__name__}: {failure}"
        ticket = await container.tickets.ticket(_ticket_id(task))
        transcript: list[TicketMessage] = list(ticket.messages) if ticket is not None else []
        db_match = canonical_hash(await container.retail.snapshot()) == gold
        verdicts: list[AssertionVerdict] = []
        judged = None
        if error is None:
            try:
                verdicts, judged = await judge_assertions(container.models, task.nl_assertions, transcript)
            except Exception as failure:  # a judge that cannot answer fails the trial, not the run
                error = f"judging failed: {type(failure).__name__}: {failure}"
        events = await container.events.read_after(0, limit=100_000)
        cost = _model_spend(events) + (judged.cost_usd(container.models.price("qa")) if judged else 0.0)
        input_tokens, cached_tokens = _agent_input(events)
        tool_calls = [
            f"{event.payload.get('tool')}({json.dumps(event.payload.get('arguments'))})"
            f"{'' if event.payload.get('ok') else ' -> error'}"
            for event in events
            if event.kind is EventKind.TOOL_CALLED
        ]
    assertions_met = all(verdict.met for verdict in verdicts)
    return TrialResult(
        task_id=task.task_id,
        trial=trial,
        reward=reward(task, db_match=db_match, assertions_met=assertions_met) if error is None else 0.0,
        db_match=db_match,
        assertions=verdicts,
        outcome=outcome,
        approvals=approvals,
        customer_turns=sum(message.author == "customer" for message in transcript),
        cost_usd=round(cost, 6),
        seconds=round((clock.now() - began).total_seconds(), 1),
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        error=error,
        tool_calls=tool_calls,
        transcript=[f"{message.author}: {message.body}" for message in transcript],
    )


async def _converse(container: Container, task: Tau3Task) -> tuple[str, int]:
    queue = container.inprocess_queue
    assert queue is not None
    greeting = TicketMessage(author="agent", body=GREETING, created_at=container.clock.now())
    brief: dict[str, JsonValue] = {
        "scenario": scenario(
            task.reason_for_call, task.known_info, task.unknown_info, task.task_instructions, persona=task.persona
        ),
        "task_id": task.task_id,
    }
    _, item = await container.commands.open_ticket(
        [greeting],
        actor="eval",
        subject=f"τ³ task {task.task_id}",
        today=load_world_config().anchor.date(),
        brief=brief,
        ticket_id=_ticket_id(task),
        wait_for_customer=True,
        owner="support",
    )
    await queue.send(CustomerTurnJob(work_item_id=item.id, position=1))
    approvals = 0
    while True:
        await queue.run_until_idle(virtual_time=True)
        pending = [a for a in await container.approvals.pending() if a.work_item_id == item.id]
        if not pending:
            break
        for approval in pending:
            approvals += 1
            decision = (
                ApprovalDecision(verdict="reject", note="Goodwill refunds are outside the policy.")
                if approval.request.action in NOT_IN_TAU3
                else ApprovalDecision(verdict="approve", note="Approved automatically during evaluation.")
            )
            await container.commands.decide_approval(approval.id, decision, actor="eval")
    status = (await container.work.get(item.id)).status
    return _OUTCOMES.get(status, status.value), approvals


_OUTCOMES: dict[WorkStatus, Literal["resolved", "escalated", "stalled"]] = {
    WorkStatus.DONE: "resolved",
    WorkStatus.ESCALATED: "escalated",
    WorkStatus.WAITING_CUSTOMER: "stalled",
}


def _ticket_id(task: Tau3Task) -> str:
    return f"tk_tau3_{task.task_id}"


def _agent_input(events: Sequence[Event]) -> tuple[int, int]:
    total = cached = 0
    for event in events:
        usage = event.payload.get("usage")
        if event.kind is not EventKind.MODEL_CALLED or event.actor == "customer" or not isinstance(usage, dict):
            continue
        read = int(usage.get("cache_read_tokens") or 0)  # pyright: ignore[reportArgumentType]
        written = int(usage.get("cache_write_tokens") or 0)  # pyright: ignore[reportArgumentType]
        total += int(usage.get("input_tokens") or 0) + read + written  # pyright: ignore[reportArgumentType]
        cached += read
    return total, cached


def _model_spend(events: Sequence[Event]) -> float:
    return sum(
        float(event.payload.get("cost_usd") or 0.0)  # pyright: ignore[reportArgumentType]
        for event in events
        if event.kind is EventKind.MODEL_CALLED
    )

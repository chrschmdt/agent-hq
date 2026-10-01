from __future__ import annotations

from datetime import timedelta

from ahq.domain import ConflictError, EventKind, NotFoundError, SimTickJob, new_job_id, new_sim_run_id
from ahq.domain.sim import SimRun, SimStatus
from ahq.ports import Baseline, Queue
from ahq.sim.scenarios import SCENARIOS
from ahq.sim.script import build_script
from ahq.sim.tick import SimDeps, control_event, run_tick

DAY = timedelta(days=1)
ACTIVE: frozenset[SimStatus] = frozenset({"running", "paused"})


class SimControl:
    def __init__(self, deps: SimDeps, baseline: Baseline, queue: Queue | None) -> None:
        self._deps = deps
        self._baseline = baseline
        self._queue = queue

    async def start(
        self,
        scenario: str,
        *,
        seed: int,
        tick_minutes: int = 5,
        tick_seconds: float = 2.0,
        agent_tickets: int = 0,
        alerts_to_agents: bool = False,
        schedule: bool = True,
    ) -> SimRun:
        if scenario not in SCENARIOS:
            raise NotFoundError(f"unknown scenario {scenario!r}; known: {', '.join(sorted(SCENARIOS))}")
        latest = await self._deps.runs.latest()
        if latest is not None and latest.status in ACTIVE:
            await self.stop(latest.run_id)
        await self._baseline.restore()

        start = self._deps.config.anchor
        store = await self._deps.retail.snapshot()
        shipments = {shipment.tracking_id: shipment for shipment in await self._deps.world.shipments()}
        script = build_script(
            SCENARIOS[scenario],
            store,
            shipments,
            await self._deps.world.order_dates(),
            self._deps.config,
            seed=seed,
            start=start,
            end=start + DAY,
        )
        now = self._deps.clock.now()
        run = SimRun(
            run_id=new_sim_run_id(),
            scenario=scenario,
            seed=seed,
            status="running",
            started_at=start,
            ends_at=start + DAY,
            sim_now=start,
            tick_no=0,
            tick_minutes=tick_minutes,
            tick_seconds=tick_seconds,
            agent_tickets=agent_tickets,
            alerts_to_agents=alerts_to_agents,
            created_at=now,
            updated_at=now,
        )
        await self._deps.runs.create(run, script)
        await self._deps.events.append([control_event(EventKind.SIM_STARTED, run)])
        change = SCENARIOS[scenario].deploy
        if change is not None and self._deps.deploys is not None:
            await self._deps.deploys.canary_change(
                change.agent, changes=change.changes, pct=change.pct, note=change.note, by="scenario"
            )
        if schedule:
            await self._schedule(run, delay=False)
        return run

    async def pause(self, run_id: str) -> SimRun:
        run = await self._require(run_id, "running")
        paused = await self._deps.runs.set_status(run.run_id, "paused")
        await self._deps.events.append([control_event(EventKind.SIM_PAUSED, paused)])
        return paused

    async def resume(self, run_id: str) -> SimRun:
        await self._require(run_id, "paused")
        running = await self._deps.runs.set_status(run_id, "running")
        await self._deps.events.append([control_event(EventKind.SIM_RESUMED, running)])
        await self._schedule(running, delay=False, resume=True)
        return running

    async def stop(self, run_id: str) -> SimRun:
        run = await self._deps.runs.get(run_id)
        if run is None:
            raise NotFoundError(f"simulator run {run_id} not found")
        if run.status not in ACTIVE:
            return run
        stopped = await self._deps.runs.set_status(run_id, "stopped")
        await self._deps.events.append([control_event(EventKind.SIM_STOPPED, stopped)])
        return stopped

    async def reset(self) -> None:
        latest = await self._deps.runs.latest()
        if latest is not None and latest.status in ACTIVE:
            await self.stop(latest.run_id)
        await self._baseline.restore()

    async def tick(self, job: SimTickJob) -> SimRun | None:
        run = await run_tick(self._deps, job.run_id, job.tick_no)
        if run is not None and run.status == "running":
            await self._schedule(run, delay=True)
        return run

    async def drive(self, run_id: str) -> SimRun:
        run = await self._require(run_id, "running")
        while run.status == "running":
            advanced = await run_tick(self._deps, run.run_id, run.tick_no)
            if advanced is None:
                raise ConflictError(f"simulator run {run_id} was changed while driving it")
            run = advanced
        return run

    async def _schedule(self, run: SimRun, *, delay: bool, resume: bool = False) -> None:
        if self._queue is None:
            return
        job = SimTickJob(run_id=run.run_id, tick_no=run.tick_no, resume=new_job_id() if resume else None)
        await self._queue.send(job, delay_seconds=run.tick_seconds if delay else None)

    async def _require(self, run_id: str, status: SimStatus) -> SimRun:
        run = await self._deps.runs.get(run_id)
        if run is None:
            raise NotFoundError(f"simulator run {run_id} not found")
        if run.status != status:
            raise ConflictError(f"simulator run {run_id} is {run.status}, not {status}")
        return run

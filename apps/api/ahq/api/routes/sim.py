from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import Field

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import StrictModel
from ahq.domain.sim import SimRun
from ahq.sim.scenarios import SCENARIOS

router = APIRouter(tags=["simulator"])


class StartSimulation(StrictModel):
    scenario: str = "normal-day"
    seed: int = 7
    tick_minutes: int = Field(default=5, ge=1, le=60)
    tick_seconds: float = Field(default=2.0, ge=0.5, le=60)
    agent_tickets: int = Field(default=0, ge=0, le=200, description="How many of the day's tickets go to the agents.")
    alerts_to_agents: bool = Field(default=False, description="Whether the delivery watch's alerts go to Ops.")


class ScenarioSummary(StrictModel):
    name: str
    description: str
    tickets: int
    agent_tickets: int
    wave_tickets: int = 0
    alerts_to_agents: bool


class SimulatorState(StrictModel):
    run: SimRun | None
    scenarios: list[ScenarioSummary]


@router.get("/api/sim")
async def simulator_state(container: ContainerDep) -> SimulatorState:
    return SimulatorState(
        run=await container.sim_runs.latest(),
        scenarios=[
            ScenarioSummary(
                name=s.name,
                description=s.description,
                tickets=s.tickets,
                agent_tickets=s.agent_tickets,
                wave_tickets=sum(wave.tickets for wave in s.waves),
                alerts_to_agents=s.delay is not None,
            )
            for s in SCENARIOS.values()
        ],
    )


@router.get("/api/sim/runs")
async def simulated_days(container: ContainerDep, _: Operator) -> list[SimRun]:
    return await container.sim_runs.runs()


@router.post("/api/sim/start", status_code=status.HTTP_201_CREATED)
async def start_simulation(body: StartSimulation, container: ContainerDep, operator: Operator) -> SimRun:
    return await container.sim.start(
        body.scenario,
        seed=body.seed,
        tick_minutes=body.tick_minutes,
        tick_seconds=body.tick_seconds,
        agent_tickets=body.agent_tickets,
        alerts_to_agents=body.alerts_to_agents,
    )


@router.post("/api/sim/{run_id}/pause")
async def pause_simulation(run_id: str, container: ContainerDep, operator: Operator) -> SimRun:
    return await container.sim.pause(run_id)


@router.post("/api/sim/{run_id}/resume")
async def resume_simulation(run_id: str, container: ContainerDep, operator: Operator) -> SimRun:
    return await container.sim.resume(run_id)


@router.post("/api/sim/{run_id}/stop")
async def stop_simulation(run_id: str, container: ContainerDep, operator: Operator) -> SimRun:
    return await container.sim.stop(run_id)


@router.post("/api/sim/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_simulation(container: ContainerDep, operator: Operator) -> Response:
    await container.sim.reset()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

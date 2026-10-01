from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from pydantic import Field, JsonValue

from ahq.config import BudgetConfig
from ahq.domain import AgentControl, CallDecision, EventKind, ModelHealth, NewEvent, StrictModel
from ahq.ports import Clock, ControlStore, EventLog


class AgentLimits(StrictModel):
    agent: str
    paused: bool
    reason: str | None = None
    changed_by: str | None = None
    changed_at: datetime | None = None
    spent_today_usd: float
    budget_usd: float | None
    calls_today: int
    errors_today: int


class LimitsView(StrictModel):
    day: date
    total_spent_usd: float
    total_budget_usd: float
    agents: list[AgentLimits]
    models: list[ModelHealth] = Field(default_factory=list)


def utc_day(moment: datetime) -> date:
    return moment.astimezone(UTC).date()


class Limiter:
    def __init__(
        self,
        store: ControlStore,
        events: EventLog,
        clock: Clock,
        config: BudgetConfig,
        fallback: Callable[[str], str | None],
    ) -> None:
        self._store = store
        self._events = events
        self._clock = clock
        self._config = config
        self._fallback = fallback

    async def before_call(self, agent: str, model: str) -> CallDecision:
        control = (await self._store.controls()).get(agent)
        if control is not None and control.paused:
            return CallDecision(verdict="pause", model=model, reason=control.reason or "paused")
        now = self._clock.now()
        lines = await self._store.spend(utc_day(now))
        total = sum(line.cost_usd for line in lines)
        mine = sum(line.cost_usd for line in lines if line.agent == agent)
        cap = self._config.daily.agents.get(agent)
        if total >= self._config.daily.total_usd or (cap is not None and mine >= cap):
            which = "all agents" if total >= self._config.daily.total_usd else agent
            reason = f"the daily budget for {which} is spent"
            await self._emit(EventKind.LIMIT_REACHED, agent, {"agent": agent, "reason": reason, "spent_usd": mine})
            return CallDecision(verdict="deny", model=model, reason=reason)
        health = await self._store.health()
        if model in health and health[model].is_open(now):
            fallback = self._fallback(model)
            if fallback is not None and not (fallback in health and health[fallback].is_open(now)):
                return CallDecision(verdict="fallback", model=fallback, reason=f"{model}'s breaker is open")
        return CallDecision(verdict="proceed", model=model)

    async def after_call(self, agent: str, model: str, *, cost_usd: float, ok: bool, error: str | None = None) -> None:
        now = self._clock.now()
        await self._store.add_spend(utc_day(now), agent, model, cost_usd=cost_usd, ok=ok)
        breaker = self._config.model_breaker
        health, opened = await self._store.record_call(
            model,
            ok=ok,
            at=now,
            errors_to_open=breaker.errors,
            cooldown=timedelta(minutes=breaker.cooldown_minutes),
            error=error,
        )
        if opened:
            payload: dict[str, JsonValue] = {
                "model": model,
                "fallback": self._fallback(model),
                "until": health.open_until.isoformat() if health.open_until else None,
                "errors": health.consecutive_errors,
                "error": error,
            }
            await self._emit(EventKind.BREAKER_OPENED, agent, payload)

    async def paused(self) -> frozenset[str]:
        return frozenset(agent for agent, control in (await self._store.controls()).items() if control.paused)

    async def pause(self, agent: str, *, by: str, reason: str) -> AgentControl:
        control = AgentControl(agent=agent, paused=True, reason=reason, changed_by=by, changed_at=self._clock.now())
        await self._store.set_control(control)
        await self._emit(EventKind.AGENT_PAUSED, by, {"agent": agent, "reason": reason})
        return control

    async def resume(self, agent: str, *, by: str) -> AgentControl:
        control = AgentControl(agent=agent, paused=False, changed_by=by, changed_at=self._clock.now())
        await self._store.set_control(control)
        await self._emit(EventKind.AGENT_RESUMED, by, {"agent": agent})
        return control

    async def view(self, agents: list[str]) -> LimitsView:
        today = utc_day(self._clock.now())
        controls = await self._store.controls()
        lines = await self._store.spend(today)
        rows: list[AgentLimits] = []
        for agent in agents:
            mine = [line for line in lines if line.agent == agent]
            control = controls.get(agent)
            rows.append(
                AgentLimits(
                    agent=agent,
                    paused=control is not None and control.paused,
                    reason=control.reason if control else None,
                    changed_by=control.changed_by if control else None,
                    changed_at=control.changed_at if control else None,
                    spent_today_usd=round(sum(line.cost_usd for line in mine), 6),
                    budget_usd=self._config.daily.agents.get(agent),
                    calls_today=sum(line.calls for line in mine),
                    errors_today=sum(line.errors for line in mine),
                )
            )
        return LimitsView(
            day=today,
            total_spent_usd=round(sum(line.cost_usd for line in lines), 6),
            total_budget_usd=self._config.daily.total_usd,
            agents=rows,
            models=sorted((await self._store.health()).values(), key=lambda health: health.model),
        )

    async def _emit(self, kind: EventKind, actor: str, payload: dict[str, JsonValue]) -> None:
        await self._events.append([NewEvent(kind=kind, occurred_at=self._clock.now(), actor=actor, payload=payload)])

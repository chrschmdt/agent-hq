from __future__ import annotations

from datetime import timedelta

from ahq.config import load_budget_config
from tests.unit.management.helpers import Desk

DAILY = load_budget_config().daily


async def test_calls_proceed_within_every_limit() -> None:
    decision = await Desk().limiter.before_call("support", "gpt-6-luna")
    assert (decision.verdict, decision.model) == ("proceed", "gpt-6-luna")


async def test_a_paused_agent_is_stopped_until_it_is_resumed() -> None:
    desk = Desk()
    await desk.limiter.pause("support", by="operator", reason="bad replies")
    assert (await desk.limiter.before_call("support", "gpt-6-luna")).verdict == "pause"
    assert await desk.limiter.paused() == {"support"}
    await desk.limiter.resume("support", by="operator")
    assert (await desk.limiter.before_call("support", "gpt-6-luna")).verdict == "proceed"
    assert (await desk.kinds()) == ["agent.paused", "agent.resumed"]


async def test_an_agent_stops_once_its_daily_budget_is_spent() -> None:
    desk = Desk()
    await desk.limiter.after_call("dispatcher", "gpt-6-luna", cost_usd=DAILY.agents["dispatcher"], ok=True)
    denied = await desk.limiter.before_call("dispatcher", "gpt-6-luna")
    assert (denied.verdict, denied.reason) == ("deny", "the daily budget for dispatcher is spent")
    assert (await desk.limiter.before_call("support", "gpt-6-luna")).verdict == "proceed"
    desk.clock.advance(timedelta(days=1))
    assert (await desk.limiter.before_call("dispatcher", "gpt-6-luna")).verdict == "proceed"


async def test_all_agents_stop_once_the_total_budget_is_spent() -> None:
    desk = Desk()
    left = DAILY.total_usd
    for agent, cap in DAILY.agents.items():
        cost = min(cap * 0.99, left)
        await desk.limiter.after_call(agent, "gpt-6-luna", cost_usd=cost, ok=True)
        left -= cost
    assert left <= 0
    denied = await desk.limiter.before_call("support", "gpt-6-luna")
    assert (denied.verdict, denied.reason) == ("deny", "the daily budget for all agents is spent")


async def test_three_failures_in_a_row_send_calls_to_the_fallback_until_the_cooldown_ends() -> None:
    desk = Desk()
    for _ in range(3):
        await desk.limiter.after_call("support", "claude-haiku-4-5", cost_usd=0.0, ok=False, error="overloaded")

    fallback = await desk.limiter.before_call("support", "claude-haiku-4-5")
    assert (fallback.verdict, fallback.model) == ("fallback", "gpt-6-luna")
    assert (await desk.kinds()).count("breaker.opened") == 1
    desk.clock.advance(timedelta(minutes=11))
    assert (await desk.limiter.before_call("support", "claude-haiku-4-5")).verdict == "proceed"


async def test_the_view_shows_switches_spend_and_breakers() -> None:
    desk = Desk()
    await desk.limiter.after_call("support", "gpt-6-luna", cost_usd=0.25, ok=True)
    await desk.limiter.after_call("support", "gpt-6-luna", cost_usd=0.0, ok=False)
    await desk.limiter.pause("ops", by="operator", reason="checking")
    view = await desk.limiter.view(["support", "ops"])
    support, ops = view.agents
    assert (support.spent_today_usd, support.calls_today, support.errors_today, support.budget_usd) == (
        0.25,
        2,
        1,
        DAILY.agents["support"],
    )
    assert (ops.paused, ops.reason) == (True, "checking")
    assert [health.model for health in view.models] == ["gpt-6-luna"]

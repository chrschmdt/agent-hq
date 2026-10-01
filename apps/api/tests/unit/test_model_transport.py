from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import httpx2
import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory_management import MemorySlots
from ahq.adapters.openrouter.chat import GovernedChatAnthropic
from ahq.adapters.openrouter.transport import (
    GovernedHttpxTransport,
    GovernedTransport,
    Governor,
    provider_of,
    retry_after,
)
from ahq.config import CallPolicy
from ahq.domain import RetryLater, deferral

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
POLICY = CallPolicy(
    slots={"openai": 2},
    default_slots=3,
    lease_seconds=60,
    wait_seconds=5,
    attempts=4,
    backoff_seconds=1.0,
    max_wait_seconds=30,
)
OPENAI_REPLY = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 0,
    "model": "openai/gpt-6-luna",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
}
ANTHROPIC_REPLY = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "anthropic/claude-haiku-4.5",
    "content": [{"type": "text", "text": "Hello."}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 3, "output_tokens": 2},
}


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def answers(
    *statuses: int, headers: dict[str, str] | None = None, body: object = None
) -> Callable[[httpx2.Request], httpx2.Response]:
    remaining = list(statuses)

    def handle(request: httpx2.Request) -> httpx2.Response:
        status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return httpx2.Response(status, json=body if status == 200 else {"error": "busy"}, headers=headers or {})

    return handle


def governor(sleeps: Sleeps, *, slots: MemorySlots | None = None, jitter: float = 0.5) -> Governor:
    return Governor("openai", POLICY, ManualClock(NOW), slots=slots, sleep=sleeps, jitter=lambda: jitter)


async def send(transport: GovernedTransport) -> httpx2.Response:
    async with httpx2.AsyncClient(transport=transport, base_url="https://openrouter.test") as client:
        return await client.post("/v1/chat/completions", json={})


async def test_a_busy_answer_is_retried_after_a_jittered_wait() -> None:
    sleeps = Sleeps()
    transport = GovernedTransport(governor(sleeps), httpx2.MockTransport(answers(429, 503, 200, body={"ok": 1})))
    response = await send(transport)
    assert response.status_code == 200
    assert sleeps.waits == [0.5, 1.0]


async def test_a_retry_waits_at_least_as_long_as_the_provider_asks() -> None:
    sleeps = Sleeps()
    handler = answers(429, 200, headers={"retry-after": "3"}, body={"ok": 1})
    await send(GovernedTransport(governor(sleeps), httpx2.MockTransport(handler)))
    assert sleeps.waits == [3.0]


async def test_a_provider_that_stays_busy_defers_the_work() -> None:
    sleeps = Sleeps()
    with pytest.raises(RetryLater) as raised:
        await send(GovernedTransport(governor(sleeps), httpx2.MockTransport(answers(429))))
    assert len(sleeps.waits) == POLICY.attempts - 1
    assert raised.value.reason == "openai answered 429"


async def test_a_long_retry_after_defers_at_once() -> None:
    sleeps = Sleeps()
    handler = answers(429, headers={"retry-after": "120"})
    with pytest.raises(RetryLater) as raised:
        await send(GovernedTransport(governor(sleeps), httpx2.MockTransport(handler)))
    assert sleeps.waits == []
    assert raised.value.after_seconds == 120.0


async def test_other_errors_are_not_retried() -> None:
    sleeps = Sleeps()
    response = await send(GovernedTransport(governor(sleeps), httpx2.MockTransport(answers(400))))
    assert response.status_code == 400
    assert sleeps.waits == []


def test_full_jitter_stays_under_the_doubling_ceiling() -> None:
    gate = governor(Sleeps(), jitter=1.0)
    assert [gate.wait(attempt, None) for attempt in range(7)] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert governor(Sleeps(), jitter=0.0).wait(3, 2.5) == 2.5


@pytest.mark.parametrize(
    ("headers", "seconds"),
    [
        ({"retry-after": "2"}, 2.0),
        ({"retry-after-ms": "1500"}, 1.5),
        ({"retry-after": format_datetime(NOW + timedelta(seconds=9), usegmt=True)}, 9.0),
        ({"retry-after": "soon"}, None),
        ({}, None),
    ],
)
def test_retry_after_is_read_in_every_form(headers: dict[str, str], seconds: float | None) -> None:
    assert retry_after(httpx.Headers(headers), NOW) == seconds


async def test_calls_in_flight_never_exceed_the_providers_slots() -> None:
    slots = MemorySlots()
    in_flight = 0
    most = 0

    async def slow(request: httpx2.Request) -> httpx2.Response:
        nonlocal in_flight, most
        in_flight += 1
        most = max(most, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx2.Response(200, json={})

    gate = Governor("openai", POLICY, ManualClock(NOW), slots=slots, sleep=asyncio.sleep, jitter=lambda: 0.0)
    gate_transport = GovernedTransport(gate, httpx2.MockTransport(slow))
    responses = await asyncio.gather(*(send(gate_transport) for _ in range(8)))
    assert [r.status_code for r in responses] == [200] * 8
    assert most == POLICY.slots_for("openai") == 2
    assert slots.held("openai", NOW) == 0


async def test_a_call_that_finds_no_free_slot_in_time_defers() -> None:
    slots = MemorySlots()
    for holder in ("a", "b"):
        assert await slots.acquire("openai", holder, limit=2, now=NOW, until=NOW + timedelta(minutes=1))
    sleeps = Sleeps()
    with pytest.raises(RetryLater) as raised:
        await send(GovernedTransport(governor(sleeps, slots=slots), httpx2.MockTransport(answers(200, body={}))))
    assert "slots stayed busy" in raised.value.reason
    assert sum(sleeps.waits) >= POLICY.wait_seconds


async def test_our_own_httpx_clients_are_governed_too() -> None:
    sleeps = Sleeps()

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429 if not sleeps.waits else 200, json={})

    transport = GovernedHttpxTransport(governor(sleeps), httpx.MockTransport(handle))
    async with httpx.AsyncClient(transport=transport, base_url="https://openrouter.test") as client:
        assert (await client.post("/v1/rerank", json={})).status_code == 200
    assert len(sleeps.waits) == 1


async def test_the_openai_sdk_retries_nothing_itself_and_surfaces_the_deferral() -> None:
    sleeps = Sleeps()
    requests: list[int] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(1)
        return httpx2.Response(429, json={"error": {"message": "busy"}})

    client = httpx2.AsyncClient(transport=GovernedTransport(governor(sleeps), httpx2.MockTransport(handle)))
    model = ChatOpenAI(
        model="openai/gpt-6-luna",
        base_url="https://openrouter.test/api/v1",
        api_key=SecretStr("key"),
        max_retries=0,
        http_async_client=client,
    )
    with pytest.raises(Exception) as raised:  # noqa: PT011
        await model.ainvoke([HumanMessage("Hi")])
    later = deferral(raised.value)
    assert later is not None
    assert later.reason == "openai answered 429"
    assert len(requests) == POLICY.attempts


async def test_both_sdks_answer_through_the_governed_transport() -> None:
    sleeps = Sleeps()
    openai_client = httpx2.AsyncClient(
        transport=GovernedTransport(governor(sleeps), httpx2.MockTransport(answers(429, 200, body=OPENAI_REPLY)))
    )
    openai = ChatOpenAI(
        model="openai/gpt-6-luna",
        base_url="https://openrouter.test/api/v1",
        api_key=SecretStr("key"),
        max_retries=0,
        http_async_client=openai_client,
    )
    assert (await openai.ainvoke([HumanMessage("Hi")])).text == "Hello."
    anthropic = GovernedChatAnthropic(
        model_name="anthropic/claude-haiku-4.5",
        base_url="https://openrouter.test/api",
        api_key=SecretStr("key"),
        max_retries=0,
        timeout=None,
        stop=None,
        transport=GovernedTransport(governor(sleeps), httpx2.MockTransport(answers(503, 200, body=ANTHROPIC_REPLY))),
    )
    assert (await anthropic.ainvoke([HumanMessage("Hi")])).text == "Hello."
    assert len(sleeps.waits) == 2


def test_the_provider_is_the_first_part_of_the_model_id() -> None:
    assert provider_of("anthropic/claude-haiku-4.5") == "anthropic"
    assert provider_of("voyageai/rerank-2.5") == "voyageai"

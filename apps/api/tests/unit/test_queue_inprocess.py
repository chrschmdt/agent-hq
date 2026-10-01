from __future__ import annotations

import asyncio

from ahq.adapters.queue_inprocess import InProcessQueue
from ahq.domain import Job, RetryLater, SegmentJob, SimTickJob, Topic, WorkItemId
from ahq.ports import Delivery


def job(n: int = 1) -> SegmentJob:
    return SegmentJob(action="start", work_item_id=WorkItemId(f"wi_{n}"))


async def test_delivers_each_job_to_its_topic_handler() -> None:
    queue = InProcessQueue()
    seen: list[str] = []

    async def handler(item: Job, delivery: Delivery) -> None:
        seen.append(item.job_id)

    queue.register(Topic.WORK, handler)
    first, second = job(1), job(2)
    await queue.send(first)
    await queue.send(second)
    assert await queue.run_until_idle() == 2
    assert seen == [first.job_id, second.job_id]


async def test_delays_order_deliveries_by_due_time() -> None:
    queue = InProcessQueue()
    seen: list[str] = []

    async def handler(item: Job, delivery: Delivery) -> None:
        seen.append(item.job_id)

    queue.register(Topic.WORK, handler)
    late, early = job(1), job(2)
    await queue.send(late, delay_seconds=30)
    await queue.send(early)
    await queue.run_until_idle()
    assert seen == [early.job_id, late.job_id]


async def test_failures_are_retried_until_they_succeed() -> None:
    queue = InProcessQueue(max_attempts=3)
    attempts: list[int] = []

    async def flaky(item: Job, delivery: Delivery) -> None:
        attempts.append(delivery.attempt)
        if delivery.attempt < 3:
            raise RuntimeError("transient")

    queue.register(Topic.WORK, flaky)
    await queue.send(job())
    await queue.run_until_idle()
    assert attempts == [1, 2, 3]
    assert queue.dead_letters == []


async def test_jobs_that_keep_failing_become_dead_letters() -> None:
    queue = InProcessQueue(max_attempts=2)

    async def broken(item: Job, delivery: Delivery) -> None:
        raise RuntimeError("permanent")

    queue.register(Topic.WORK, broken)
    await queue.send(job())
    await queue.run_until_idle()
    assert len(queue.dead_letters) == 1
    assert queue.dead_letters[0].attempts == 2


async def test_retry_later_reschedules_without_failing() -> None:
    queue = InProcessQueue(max_attempts=2)
    attempts: list[int] = []

    async def busy_then_free(item: Job, delivery: Delivery) -> None:
        attempts.append(delivery.attempt)
        if delivery.attempt == 1:
            raise RetryLater(5, "lease held")

    queue.register(Topic.WORK, busy_then_free)
    await queue.send(job())
    await queue.run_until_idle()
    assert attempts == [1, 2]
    assert queue.dead_letters == []


async def test_a_job_sent_twice_is_delivered_once() -> None:
    queue = InProcessQueue()
    seen: list[str] = []

    async def handler(item: Job, delivery: Delivery) -> None:
        seen.append(item.job_id)

    queue.register(Topic.WORK, handler)
    once = job()
    await queue.send(once)
    await queue.send(once)
    await queue.run_until_idle()
    assert seen == [once.job_id]


async def test_duplicate_delivery_mode_delivers_every_job_twice() -> None:
    queue = InProcessQueue(duplicate_deliveries=True)
    seen: list[str] = []

    async def handler(item: Job, delivery: Delivery) -> None:
        seen.append(item.job_id)

    queue.register(Topic.WORK, handler)
    await queue.send(job())
    await queue.run_until_idle()
    assert len(seen) == 2


async def test_with_concurrency_due_jobs_run_at_once_and_time_waits_for_them() -> None:
    queue = InProcessQueue()
    in_flight = 0
    most = 0
    order: list[str] = []

    async def handler(item: Job, delivery: Delivery) -> None:
        nonlocal in_flight, most
        in_flight += 1
        most = max(most, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        order.append(item.job_id)

    queue.register(Topic.WORK, handler)
    now = [job(n) for n in range(6)]
    later = job(9)
    for item in now:
        await queue.send(item)
    await queue.send(later, delay_seconds=60)
    assert await queue.run_until_idle(concurrency=4) == 7
    assert most == 4
    assert order[-1] == later.job_id


async def test_the_development_worker_runs_due_jobs_side_by_side_until_stopped() -> None:
    queue = InProcessQueue()
    both_running = asyncio.Event()
    running: set[str] = set()
    finished: list[str] = []

    async def slow(item: Job, delivery: Delivery) -> None:
        running.add(item.job_id)
        if len(running) == 2:
            both_running.set()
        await both_running.wait()
        finished.append(item.job_id)

    queue.register(Topic.WORK, slow)
    stop = asyncio.Event()
    worker = asyncio.create_task(queue.run_forever(stop, concurrency=2))
    jobs = [job(1), job(2), job(3)]
    await queue.send(jobs[0])
    await queue.send(jobs[1])
    await asyncio.wait_for(both_running.wait(), timeout=2)
    await queue.send(jobs[2], delay_seconds=0.05)
    for _ in range(100):
        if len(finished) == 3:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(worker, timeout=2)
    assert sorted(finished) == sorted(item.job_id for item in jobs)


async def test_the_development_worker_limits_each_topic_on_its_own() -> None:
    queue = InProcessQueue()
    release = asyncio.Event()
    ticked = asyncio.Event()

    async def busy(item: Job, delivery: Delivery) -> None:
        await release.wait()

    async def tick(item: Job, delivery: Delivery) -> None:
        ticked.set()

    queue.register(Topic.WORK, busy)
    queue.register(Topic.SIM, tick)
    stop = asyncio.Event()
    worker = asyncio.create_task(queue.run_forever(stop, concurrency=1))
    await queue.send(job(1))
    await queue.send(job(2))
    await queue.send(SimTickJob(run_id="sim_1", tick_no=0))
    await asyncio.wait_for(ticked.wait(), timeout=2)
    assert queue.pending == 1
    release.set()
    for _ in range(100):
        if queue.pending == 0:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(worker, timeout=2)
    assert queue.pending == 0

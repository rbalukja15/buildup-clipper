"""Worker semantics: one job at a time, failures contained, progress published."""
from __future__ import annotations

import asyncio

import pytest

from app.jobs import JobQueue


@pytest.fixture
async def worker():
    q = JobQueue()
    q.start()
    yield q
    await q.stop()


async def _drain(q: JobQueue, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while any(j["state"] in ("queued", "running") for j in q.jobs()):
            await asyncio.sleep(0.01)


async def test_jobs_run_one_at_a_time(worker):
    """ffmpeg is CPU-bound; two encodes at once on a laptop help nobody."""
    concurrent = 0
    peak = 0

    async def body(job):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.02)
        concurrent -= 1

    for i in range(4):
        await worker.submit("clip", i, f"job {i}", body)
    await _drain(worker)

    assert peak == 1
    assert [j["state"] for j in worker.jobs()] == ["done"] * 4


async def test_a_failing_job_does_not_stop_the_queue(worker):
    async def boom(job):
        raise RuntimeError("ffmpeg exploded")

    async def fine(job):
        return None

    await worker.submit("clip", 1, "bad", boom)
    await worker.submit("clip", 2, "good", fine)
    await _drain(worker)

    states = {j["entity_id"]: j for j in worker.jobs()}
    assert states[1]["state"] == "failed" and "exploded" in states[1]["error"]
    assert states[2]["state"] == "done"


async def test_progress_is_published_to_subscribers(worker):
    subscription = worker.subscribe()

    async def body(job):
        for p in (0.25, 0.5, 1.0):
            await job.set_progress(p)

    await worker.submit("export", 7, "exporting", body)
    await _drain(worker)

    progress = [e["job"]["progress"] for e in _collect(subscription) if e.get("type") == "job"]
    assert 1.0 in progress
    assert progress == sorted(progress), "progress must never go backwards"


async def test_a_stalled_subscriber_is_dropped_rather_than_blocking_the_worker(worker):
    subscription = worker.subscribe()
    for _ in range(subscription.maxsize + 5):
        await worker.publish({"type": "noise"})
    assert subscription not in worker._subscribers


def _collect(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out

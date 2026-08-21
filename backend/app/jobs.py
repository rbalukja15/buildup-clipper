"""Single in-process async worker + SSE fan-out.

One worker means ffmpeg never competes with itself for CPU on a laptop, and
job ordering is predictable: ingest, then clips, then export.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger("buc.jobs")

JobBody = Callable[["Job"], Awaitable[None]]


@dataclass
class Job:
    id: int
    kind: str                     # ingest | clip | export
    entity_id: int
    label: str
    state: str = "queued"         # queued | running | done | failed
    progress: float = 0.0
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    _queue: "JobQueue | None" = field(default=None, repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        # Built by hand rather than asdict(): the back-reference to the queue
        # must not be walked (or deep-copied) on every progress tick.
        return {
            "id": self.id,
            "kind": self.kind,
            "entity_id": self.entity_id,
            "label": self.label,
            "state": self.state,
            "progress": round(self.progress, 4),
            "error": self.error,
            "created_at": self.created_at,
        }

    async def set_progress(self, value: float) -> None:
        # Coalesce noise: only publish visible movement.
        if value < 1.0 and abs(value - self.progress) < 0.01:
            return
        self.progress = value
        if self._queue:
            await self._queue.publish({"type": "job", "job": self.public()})


class JobQueue:
    def __init__(self) -> None:
        # asyncio primitives are created in start(), inside the running loop --
        # the module-level singleton would otherwise bind to the wrong loop when
        # the app is restarted (or re-created between tests).
        self._queue: asyncio.Queue[tuple[Job, JobBody]] | None = None
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._jobs: dict[int, Job] = {}
        self._worker: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._next_id = 1

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        loop = asyncio.get_running_loop()
        if self._worker is not None and not self._worker.done() and self._loop is loop:
            return
        if self._worker is not None and self._loop is not loop:
            # Left over from a previous run of the app in this process. It
            # belongs to a loop that is gone, so it cannot be awaited -- drop it
            # rather than adopting a worker that will never run again.
            self._worker.cancel()
        self._loop = loop
        self._queue = asyncio.Queue()
        self._subscribers = set()
        self._jobs = {}
        self._next_id = 1
        self._worker = asyncio.create_task(self._run(), name="buc-worker")

    async def stop(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None and not worker.done() and self._loop is asyncio.get_running_loop():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._loop = None
        self._queue = None
        self._subscribers = set()

    # -- producer ----------------------------------------------------------
    async def submit(self, kind: str, entity_id: int, label: str, body: JobBody) -> Job:
        if self._queue is None:
            raise RuntimeError("job worker is not running")
        job = Job(id=self._next_id, kind=kind, entity_id=entity_id, label=label)
        job._queue = self
        self._next_id += 1
        self._jobs[job.id] = job
        self._trim()
        await self._queue.put((job, body))
        await self.publish({"type": "job", "job": job.public()})
        return job

    def jobs(self) -> list[dict]:
        return [j.public() for j in sorted(self._jobs.values(), key=lambda j: j.id)]

    def _trim(self, keep: int = 200) -> None:
        """Drop the oldest finished jobs so a long session does not grow forever."""
        excess = len(self._jobs) - keep
        if excess <= 0:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.state in ("done", "failed")),
            key=lambda j: j.id,
        )
        for job in finished[:excess]:
            self._jobs.pop(job.id, None)

    # -- pub/sub -----------------------------------------------------------
    def subscribe(self) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # A stalled browser tab must not block the worker.
                self._subscribers.discard(q)

    # -- consumer ----------------------------------------------------------
    async def _run(self) -> None:
        queue_ = self._queue
        assert queue_ is not None
        while True:
            job, body = await queue_.get()
            job.state = "running"
            await self.publish({"type": "job", "job": job.public()})
            try:
                await body(job)
                job.state = "done"
                job.progress = 1.0
            except asyncio.CancelledError:
                job.state = "failed"
                job.error = "cancelled"
                await self.publish({"type": "job", "job": job.public()})
                raise
            except Exception as exc:  # noqa: BLE001 -- surfaced to the UI
                log.exception("job %s failed", job.id)
                job.state = "failed"
                job.error = str(exc)
            finally:
                queue_.task_done()
            await self.publish({"type": "job", "job": job.public()})


queue = JobQueue()


async def notify(entity: str, entity_id: int | None = None) -> None:
    """Tell connected clients that a row changed and they should refetch."""
    await queue.publish({"type": "changed", "entity": entity, "id": entity_id})

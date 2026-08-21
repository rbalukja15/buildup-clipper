"""Server-sent events: job progress and row-change pings."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import StreamingResponse

from ..jobs import queue

router = APIRouter(prefix="/api", tags=["events"])

HEARTBEAT_S = 15


@router.get("/jobs")
def list_jobs() -> list[dict]:
    return queue.jobs()


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    subscription = queue.subscribe()

    async def stream():
        try:
            yield _sse({"type": "hello", "jobs": queue.jobs()})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(subscription.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # keeps proxies from closing the stream
                    continue
                yield _sse(event)
        finally:
            queue.unsubscribe(subscription)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no", "connection": "keep-alive"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

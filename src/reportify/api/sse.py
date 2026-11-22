"""Server-Sent Events for run execution (07 §6).

Frames are built from persisted ``run_event`` rows; a client that reconnects with
``Last-Event-ID`` gets the tail it missed, then live events.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi.responses import StreamingResponse

from reportify.core.events import TERMINAL_EVENTS, EventPublisher, RunEventView

HEARTBEAT_SECONDS = 15
HEARTBEAT_FRAME = ": keep-alive\n\n"


def format_event(event: RunEventView) -> str:
    body = json.dumps(event.payload, ensure_ascii=False, default=str)
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {body}\n\n"


def parse_last_event_id(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return 0
    return max(0, value)


async def event_stream(
    publisher: EventPublisher,
    run_id: UUID,
    *,
    after_sequence: int = 0,
) -> AsyncIterator[str]:
    broker = publisher.broker
    async with broker.subscribe(run_id) as queue:
        seen = after_sequence
        replayed = await publisher.replay(run_id, after_sequence)
        for event in replayed:
            seen = max(seen, event.sequence)
            yield format_event(event)
        if any(event.event_type in TERMINAL_EVENTS for event in replayed):
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield HEARTBEAT_FRAME
                continue
            if event is None:
                return
            if event.sequence <= seen:
                continue
            seen = event.sequence
            yield format_event(event)
            if event.event_type in TERMINAL_EVENTS:
                return


def sse_response(
    publisher: EventPublisher,
    run_id: UUID,
    *,
    after_sequence: int = 0,
) -> StreamingResponse:
    return StreamingResponse(
        event_stream(publisher, run_id, after_sequence=after_sequence),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

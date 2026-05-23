"""In-process event channel + tick scheduler.

The channel is a single `asyncio.Queue` of `OrchestratorEvent`s. Triggers
(tick scheduler, webhook handlers, control API) push events onto the
queue; the agent runner pops them one at a time.

Bounded queue (default 32) so a runaway producer can't OOM the process —
producers see `QueueFull` and the orchestrator emits an audit row.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator

import structlog

from .types import OrchestratorEvent, TickEvent


_log = structlog.get_logger("versawiki_orchestrator.events")


class EventChannel:
    """asyncio.Queue wrapped with `put_event` / `iterate` helpers.

    The agent runner consumes via `async for event in channel.iterate():`.
    """

    def __init__(self, *, maxsize: int = 32) -> None:
        self._q: asyncio.Queue[OrchestratorEvent] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def put_event(self, event: OrchestratorEvent) -> bool:
        """Push an event. Returns False if the queue is full (event dropped)."""
        if self._closed:
            return False
        try:
            self._q.put_nowait(event)
            return True
        except asyncio.QueueFull:
            _log.warning(
                "event_channel_full",
                event_id=event.event_id,
                kind=event.kind,
                qsize=self._q.qsize(),
            )
            return False

    async def iterate(self) -> AsyncIterator[OrchestratorEvent]:
        """Yield events as they arrive. Exits when `close()` is called."""
        while not self._closed:
            try:
                event = await asyncio.wait_for(self._q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            yield event

    def qsize(self) -> int:
        return self._q.qsize()

    def close(self) -> None:
        self._closed = True


async def run_tick_scheduler(
    channel: EventChannel, *, interval_seconds: int
) -> None:
    """Push a `TickEvent` every `interval_seconds`.

    Cancellable: the wrapping `asyncio.Task` is cancelled at shutdown.
    Uses `asyncio.sleep` rather than scheduled times to avoid drift
    accumulating across long runs — accuracy of a couple seconds per tick
    is fine for our use case.
    """
    import time as _time

    last_tick_ns = _time.time_ns()
    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
        now_ns = _time.time_ns()
        since = (now_ns - last_tick_ns) / 1e9
        last_tick_ns = now_ns
        with contextlib.suppress(Exception):
            await channel.put_event(TickEvent(since_last_tick_s=since))

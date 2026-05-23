"""Event subscriber Protocol + in-process v1 implementation.

The collector reads raw events from an `EventSubscriber`. v1 only has the
in-process variant (a Python `asyncio.Queue` between the ingestion worker
and the collector, same process). Postgres LISTEN/NOTIFY (`M1-MCP-02b`) and
Redis Streams (`M1-MCP-02c`) will plug in here without the collector
caring.

Protocol contract:

  * `iter_events()` is an async iterator. It yields raw events as they
    arrive and never returns under normal operation. A subscriber may
    return when explicitly closed (this lets tests drain a fixed batch).
  * Cancellation: callers should run the iterator inside an asyncio task
    and `task.cancel()` to stop it. Subscribers must propagate
    `CancelledError`.
  * The iterator emits *parsed* `RawIngestionEvent` instances. Parsing
    (e.g., from a JSON byte stream) happens inside the subscriber, not in
    the collector. That keeps the collector transport-agnostic.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol, runtime_checkable

from .raw_event import RawIngestionEvent


@runtime_checkable
class EventSubscriber(Protocol):
    """Source of raw ingestion events. v1 is in-process queue."""

    def iter_events(self) -> AsyncIterator[RawIngestionEvent]:  # pragma: no cover - Protocol
        ...


class InProcessSubscriber:
    """`asyncio.Queue` backed subscriber. The ingestion worker `put`s
    raw events; the collector `iter_events` `get`s them.

    A sentinel `None` placed on the queue signals end-of-stream — tests
    use this to drain a fixed number of events. In production the queue
    is open-ended and the collector runs inside an asyncio task that is
    explicitly cancelled at shutdown.
    """

    _SENTINEL = None

    def __init__(self, maxsize: int = 0) -> None:
        # maxsize=0 = unbounded (the default). Callers that want
        # back-pressure can pass a positive integer.
        self._queue: asyncio.Queue[RawIngestionEvent | None] = asyncio.Queue(
            maxsize=maxsize
        )
        self._closed = False

    async def publish(self, event: RawIngestionEvent) -> None:
        """Put an event on the queue. Raises RuntimeError if closed."""

        if self._closed:
            raise RuntimeError("publish() on a closed subscriber")
        await self._queue.put(event)

    async def close(self) -> None:
        """Signal end-of-stream. After this, `iter_events` will drain the
        remaining queue contents and then stop.
        """

        if self._closed:
            return
        self._closed = True
        await self._queue.put(self._SENTINEL)

    async def iter_events(self) -> AsyncIterator[RawIngestionEvent]:
        """Async iterator over queued events. Stops at the sentinel."""

        while True:
            event = await self._queue.get()
            if event is self._SENTINEL:
                # Put it back so a second consumer (rare) also sees the
                # signal. In practice we have one consumer.
                await self._queue.put(self._SENTINEL)
                return
            yield event

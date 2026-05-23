"""`InProcessSubscriber`: producer/consumer round-trip and order preservation."""

from __future__ import annotations

import asyncio

import pytest

from versawiki_meta_mcp.events.raw_event import RawOntologyShapeEvent
from versawiki_meta_mcp.events.subscriber import EventSubscriber, InProcessSubscriber


SAFE_ANON_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


def _run(awaitable):
    return asyncio.run(awaitable)


def _make_raw(i: int) -> RawOntologyShapeEvent:
    return RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID,
        depth=1,
        node_count=i,  # carry a sequence number we can assert on
        branching_factors=[],
        kind_distribution={},
    )


def test_produces_and_consumes_in_order():
    sub = InProcessSubscriber()

    async def go():
        for i in range(10):
            await sub.publish(_make_raw(i))
        await sub.close()

        seen: list[int] = []
        async for ev in sub.iter_events():
            seen.append(ev.node_count)
        return seen

    seen = _run(go())
    assert seen == list(range(10))


def test_publish_after_close_raises():
    sub = InProcessSubscriber()

    async def go():
        await sub.close()
        with pytest.raises(RuntimeError):
            await sub.publish(_make_raw(0))

    _run(go())


def test_iter_events_stops_at_close_when_no_more_events():
    sub = InProcessSubscriber()

    async def go():
        await sub.close()
        out = [ev async for ev in sub.iter_events()]
        return out

    assert _run(go()) == []


def test_satisfies_protocol():
    """Runtime-checkable Protocol confirms `InProcessSubscriber` matches."""

    sub = InProcessSubscriber()
    assert isinstance(sub, EventSubscriber)


def test_producer_consumer_interleaved():
    """Producer keeps publishing while consumer is reading; nothing dropped."""

    sub = InProcessSubscriber()

    async def producer():
        for i in range(20):
            await sub.publish(_make_raw(i))
            # Yield control so the consumer task can run.
            await asyncio.sleep(0)
        await sub.close()

    async def consumer():
        seen = []
        async for ev in sub.iter_events():
            seen.append(ev.node_count)
        return seen

    async def go():
        cons_task = asyncio.create_task(consumer())
        await producer()
        return await cons_task

    seen = _run(go())
    assert seen == list(range(20))

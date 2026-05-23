"""EventChannel tests."""

from __future__ import annotations

import asyncio

import pytest

from versawiki_orchestrator.events import EventChannel
from versawiki_orchestrator.events.types import ManualEvent, TickEvent


async def test_put_and_iterate() -> None:
    ch = EventChannel()
    assert await ch.put_event(ManualEvent(instruction="hi"))

    events = []

    async def consume() -> None:
        async for e in ch.iterate():
            events.append(e)
            if len(events) >= 1:
                ch.close()
                return

    await asyncio.wait_for(consume(), timeout=3.0)
    assert len(events) == 1
    assert events[0].kind == "manual"


async def test_put_returns_false_when_full() -> None:
    ch = EventChannel(maxsize=2)
    assert await ch.put_event(TickEvent())
    assert await ch.put_event(TickEvent())
    assert not await ch.put_event(TickEvent())  # third one drops
    ch.close()


async def test_qsize_reflects_pending() -> None:
    ch = EventChannel()
    await ch.put_event(TickEvent())
    await ch.put_event(TickEvent())
    assert ch.qsize() == 2
    ch.close()


async def test_closed_channel_drops_events() -> None:
    ch = EventChannel()
    ch.close()
    assert not await ch.put_event(TickEvent())


def test_tick_event_to_prompt_mentions_status_and_backlog() -> None:
    p = TickEvent().to_prompt()
    assert "STATUS.md" in p
    assert "BACKLOG.md" in p
    # The hard "no main push" instruction must be in the per-tick prompt
    # so it's reinforced every fire.
    assert "main" in p


def test_manual_event_uses_instruction() -> None:
    e = ManualEvent(instruction="do the thing")
    assert e.to_prompt() == "do the thing"


def test_manual_event_empty_falls_back() -> None:
    e = ManualEvent(instruction="")
    p = e.to_prompt()
    assert "no instruction" in p.lower()

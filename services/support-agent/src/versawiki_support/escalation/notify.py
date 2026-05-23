"""Notifier protocol + stub.

Production wires Slack/email; v1 ships only a stub that records calls
in memory for tests. Adding the real backend is a one-class swap.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .queue import EscalationEntry


@runtime_checkable
class Notifier(Protocol):
    def notify(self, entry: EscalationEntry) -> None: ...


class StubNotifier:
    """Captures escalations for inspection. No external calls."""

    def __init__(self) -> None:
        self.sent: list[EscalationEntry] = []

    def notify(self, entry: EscalationEntry) -> None:
        self.sent.append(entry)


__all__ = ["Notifier", "StubNotifier"]

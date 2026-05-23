"""Event shapes that flow through the orchestrator's in-process channel.

A frozen dataclass per event variant keeps things obvious for now. If/when
we want to ship events over the wire (e.g. a Postgres LISTEN-fed external
queue), these become Pydantic models with a discriminator and a
to_prompt() that emits the agent's user message.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


def _new_event_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class OrchestratorEvent:
    """Common base. Subtypes set `kind` and any extra fields."""

    kind: str
    event_id: str = field(default_factory=_new_event_id)
    received_at_ns: int = field(default_factory=time.time_ns)

    def to_prompt(self) -> str:
        """Render the agent's user-turn message for this event.

        Subclasses override; the base implementation is a sensible fallback
        so a future event type that hasn't yet customised this still works.
        """
        return f"OrchestratorEvent fired: kind={self.kind} event_id={self.event_id}"


@dataclass(frozen=True)
class TickEvent(OrchestratorEvent):
    """The cron tick. Tells the agent to look at STATUS.md and pick a ticket."""

    kind: str = "tick"
    # Wall-clock interval in seconds since the last tick fired. Useful for
    # the agent's prompt ("you last ran N seconds ago").
    since_last_tick_s: float = 0.0

    def to_prompt(self) -> str:
        return (
            "Tick fired. Read `STATUS.md` in the repo workdir. If anything is "
            "in-flight, leave it alone. Otherwise pick the topmost item from "
            "BACKLOG.md's overnight safe list that's not already in Done. "
            "Branch as `vw-agent/<ticket-id>`, implement, run tests, push the "
            "branch, open a PR. Do not push to main. Do not chain tickets — "
            "one ticket per tick."
        )


@dataclass(frozen=True)
class ManualEvent(OrchestratorEvent):
    """Operator-issued event (via the control API)."""

    kind: str = "manual"
    instruction: str = ""

    def to_prompt(self) -> str:
        return self.instruction or "Manual trigger with no instruction."

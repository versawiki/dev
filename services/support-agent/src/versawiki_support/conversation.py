"""Conversation domain model.

A Conversation is one customer thread. It is channel-agnostic: a single
Conversation may have been started by an email and continued via web
(``channel`` records the latest source).

State machine (loosely):

    open -> awaiting_customer -> open
    open -> resolved_by_agent     (terminal for the agent loop)
    open -> escalated             (terminal; humans take over)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .messages import Message


Channel = Literal["email", "web", "api"]
ConversationStatus = Literal[
    "open",
    "resolved_by_agent",
    "escalated",
    "awaiting_customer",
]


def _new_id() -> str:
    return f"conv_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(BaseModel):
    """One customer support thread."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_id)
    tenant_id: str | None = Field(
        default=None,
        description=(
            "Owning tenant id, or null for prospect / free-tier inquiries "
            "where the customer is not yet authenticated."
        ),
    )
    channel: Channel = "web"
    messages: list[Message] = Field(default_factory=list)
    status: ConversationStatus = "open"
    opened_at: datetime = Field(default_factory=_now)
    last_updated: datetime = Field(default_factory=_now)
    escalation_reason: str | None = None
    customer_identifier: str | None = Field(
        default=None,
        description=(
            "Email/handle of the customer. Used by intake adapters to "
            "thread inbound messages. Not load-bearing for auth."
        ),
    )

    # ---- mutation helpers ----

    def append(self, message: Message) -> None:
        self.messages.append(message)
        self.last_updated = _now()

    def mark_resolved(self) -> None:
        self.status = "resolved_by_agent"
        self.last_updated = _now()

    def mark_escalated(self, reason: str) -> None:
        self.status = "escalated"
        self.escalation_reason = reason
        self.last_updated = _now()

    def mark_awaiting_customer(self) -> None:
        self.status = "awaiting_customer"
        self.last_updated = _now()


__all__ = ["Conversation", "Channel", "ConversationStatus"]

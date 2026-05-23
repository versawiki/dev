"""Inbound email channel.

v1 polls an IMAP inbox; production swaps for the provider's webhook
(SendGrid Inbound Parse, Postmark, etc). The Protocol :class:`ImapClient`
lets tests inject a fake without touching imaplib.

Each unread email becomes (or extends) a Conversation. We thread by
``customer_identifier`` (the sender's address) when no In-Reply-To
header is available; otherwise by In-Reply-To. The agent processes
the message and the reply is queued for the SMTP sender (not built
here — that's the next ticket).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol, runtime_checkable

from ..agent import AgentResponse, SupportAgent
from ..conversation import Conversation


@dataclass
class FetchedEmail:
    """One inbound email reduced to what the agent needs."""

    message_id: str
    sender: str
    subject: str
    body: str
    in_reply_to: str | None = None


@runtime_checkable
class ImapClient(Protocol):
    """Minimal IMAP surface we depend on."""

    def fetch_unread(self) -> Iterable[FetchedEmail]: ...

    def mark_read(self, message_id: str) -> None: ...


@dataclass
class QueuedReply:
    """One outbound reply the SMTP sender will pick up."""

    to: str
    in_reply_to: str
    subject: str
    body: str
    conversation_id: str


@dataclass
class EmailPoller:
    """Drives one polling pass.

    Threading model: an in-memory dict of sender -> Conversation. v1
    keeps the dict in process; production uses the store's lookup by
    customer_identifier.
    """

    client: ImapClient
    agent: SupportAgent
    _threads: dict[str, Conversation] = field(default_factory=dict)
    sent_replies: list[QueuedReply] = field(default_factory=list)

    def poll_once(self) -> list[AgentResponse]:
        """Drain unread emails, return one AgentResponse per email."""
        out: list[AgentResponse] = []
        for email in self.client.fetch_unread():
            conv = self._threads.get(email.sender)
            if conv is None:
                conv = Conversation(
                    channel="email",
                    customer_identifier=email.sender,
                )
                self._threads[email.sender] = conv
            full_text = (
                f"Subject: {email.subject}\n\n{email.body}".strip()
                if email.subject
                else email.body
            )
            response = self.agent.handle_customer_text(conv, full_text)
            out.append(response)
            self.sent_replies.append(
                QueuedReply(
                    to=email.sender,
                    in_reply_to=email.message_id,
                    subject=f"Re: {email.subject}" if email.subject else "Re:",
                    body=response.reply_text,
                    conversation_id=conv.id,
                )
            )
            self.client.mark_read(email.message_id)
        return out


__all__ = ["EmailPoller", "FetchedEmail", "ImapClient", "QueuedReply"]

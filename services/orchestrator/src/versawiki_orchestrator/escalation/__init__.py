"""Escalation channels (email for v0; Telegram/SMS deferred)."""

from .email import EmailEscalator, EscalationError

__all__ = ["EmailEscalator", "EscalationError"]

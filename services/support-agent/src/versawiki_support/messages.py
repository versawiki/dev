"""Message domain model + PII redactor.

The redactor is deliberately conservative: better to leave a string
alone than to mangle it. We redact only patterns we are confident about
(credit cards, obvious bearer tokens, SSNs in US format). Tests cover
the load-bearing cases.

The redactor is a static helper, not LLM-based, so it cannot leak
inbound text. Anything we don't catch here will still pass through the
LLM's system-prompt-level instruction to not echo sensitive data — but
the static layer is the load-bearing one.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MessageRole = Literal["customer", "agent", "system"]


class Message(BaseModel):
    """One message in a Conversation.

    ``redacted=True`` means the PII redactor rewrote ``text`` before
    persisting. The original is dropped on purpose — we don't want
    inbound credit-card numbers in our JSONL.
    """

    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    redacted: bool = False


# ---------------------------------------------------------------------------
# PII redactor
# ---------------------------------------------------------------------------

# Order matters: longer-specific patterns first so we don't double-redact.
# We intentionally do NOT redact email addresses (customers use them as
# identifiers when reporting issues) or short numeric strings (a 4-digit
# error code is not PII).
_CREDIT_CARD_RE = re.compile(
    r"\b(?:\d[ -]?){13,19}\b",
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_BEARER_TOKEN_RE = re.compile(
    r"\b(?:vw|sk|pk)_[A-Za-z0-9_\-]{8,}\b",
)


def _looks_like_credit_card(candidate: str) -> bool:
    """Luhn check. Avoids redacting random 13-digit IDs."""
    digits = [int(c) for c in candidate if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, bool]:
    """Return ``(redacted_text, was_redacted)``.

    Conservative: only rewrites strings we are confident about.
    """
    redacted = text
    changed = False

    def _cc_sub(match: re.Match[str]) -> str:
        nonlocal changed
        if _looks_like_credit_card(match.group(0)):
            changed = True
            return "[REDACTED:CC]"
        return match.group(0)

    redacted = _CREDIT_CARD_RE.sub(_cc_sub, redacted)

    def _ssn_sub(_match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return "[REDACTED:SSN]"

    redacted = _SSN_RE.sub(_ssn_sub, redacted)

    def _bearer_sub(match: re.Match[str]) -> str:
        nonlocal changed
        raw = match.group(0)
        # Preserve the namespace and prefix portion when it's a vw_ key
        # (the prefix is non-secret per services/api/.../keys.py); redact
        # only the secret tail.
        parts = raw.split("_", 2)
        if len(parts) == 3 and parts[0] == "vw" and len(parts[2]) >= 8:
            changed = True
            return f"vw_{parts[1]}_[REDACTED]"
        changed = True
        return "[REDACTED:TOKEN]"

    redacted = _BEARER_TOKEN_RE.sub(_bearer_sub, redacted)

    return redacted, changed


def new_customer_message(text: str) -> Message:
    """Build a Message with PII redaction applied to a customer string."""
    redacted_text, was_redacted = redact_pii(text)
    return Message(role="customer", text=redacted_text, redacted=was_redacted)


__all__ = ["Message", "MessageRole", "redact_pii", "new_customer_message"]

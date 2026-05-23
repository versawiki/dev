"""LLM protocol + stub + Anthropic adapter.

The Protocol is the only thing the agent talks to. Tests inject a
:class:`StubSupportLLM` that returns scripted responses; production
wires :class:`AnthropicSupport` (claude-sonnet-4-6).

The LLM's contract is structured:

    SupportLLMResponse(
        reply_text=str,           # what to say to the customer
        tool_calls=[ToolCall, ...],
        confidence=float,         # 0..1
        escalate=bool,            # explicit escalation request
        escalation_reason=str | None,
        escalation_severity=str | None,
    )

The agent then validates tool_calls against the safe-actions allow-list
and the forbidden-actions deny-list before any handler runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .conversation import Conversation
from .knowledge_base import KBArticle


@dataclass
class ToolCall:
    """One requested tool invocation."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class SupportLLMResponse:
    """Structured response from the LLM."""

    reply_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    confidence: float = 1.0
    escalate: bool = False
    escalation_reason: str | None = None
    escalation_severity: str | None = None


@runtime_checkable
class SupportLLM(Protocol):
    """Protocol for the support-agent LLM driver."""

    def reply(
        self,
        conversation: Conversation,
        kb_matches: list[KBArticle],
        system_prompt: str,
    ) -> SupportLLMResponse:
        ...


# ---------------------------------------------------------------------------
# Stub for tests
# ---------------------------------------------------------------------------

class StubSupportLLM:
    """Returns scripted responses. Tests push responses with ``queue``.

    If the queue is empty, returns a low-confidence fallback that
    escalates — exactly what we want the real agent to do when an
    LLM call fails. Tests rely on this default.
    """

    def __init__(self) -> None:
        self._queue: list[SupportLLMResponse] = []
        self.calls: list[tuple[Conversation, list[KBArticle], str]] = []

    def queue(self, response: SupportLLMResponse) -> None:
        self._queue.append(response)

    def reply(
        self,
        conversation: Conversation,
        kb_matches: list[KBArticle],
        system_prompt: str,
    ) -> SupportLLMResponse:
        self.calls.append((conversation, list(kb_matches), system_prompt))
        if not self._queue:
            return SupportLLMResponse(
                reply_text=(
                    "I'm not sure how to help with that yet — let me "
                    "pass this to a teammate."
                ),
                confidence=0.0,
                escalate=True,
                escalation_reason="stub fallback (no scripted response)",
                escalation_severity="low",
            )
        return self._queue.pop(0)


# ---------------------------------------------------------------------------
# Anthropic adapter (claude-sonnet-4-6)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are versawiki's autonomous customer support agent. You handle most
customer questions directly and escalate the rest.

Hard rules (NEVER violate):

1. You do not have authority to delete data, issue refunds or credits,
   change billing, modify privacy settings, perform cross-tenant
   lookups, or take any action not on the allow-list below. If asked,
   you politely refuse and escalate.
2. You never reveal an API key hash, raw token (except the new one
   returned by reissue_api_key exactly once to the verified owner),
   another tenant's data, or internal infrastructure details.
3. If your confidence is below 0.7, escalate rather than guess.
4. PII like credit card numbers, SSNs, and bearer tokens are redacted
   from inbound messages before you see them. Do not ask the customer
   to re-send them.

Allow-listed actions (the only tools you may call):
{safe_actions}

Forbidden topics (refuse + escalate):
{forbidden_actions}

When you reply, return:
- a short, helpful answer in plain language
- any tool calls you want to make
- a confidence score in [0, 1]
- escalate=true if you cannot handle this on your own

Relevant knowledge base entries are provided below; cite them if
useful.
"""


class AnthropicSupport:
    """Thin wrapper around the Anthropic SDK.

    Not exercised by tests (we use :class:`StubSupportLLM`). The real
    LLM call wires Claude tools to the safe-actions list and demands a
    JSON-shaped final answer. ``api_key`` defaults to the
    ``ANTHROPIC_API_KEY`` env var.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
    ) -> None:
        self.model = model
        if client is not None:
            self._client = client
        else:  # pragma: no cover - exercised only with a live key
            from anthropic import Anthropic

            self._client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def reply(
        self,
        conversation: Conversation,
        kb_matches: list[KBArticle],
        system_prompt: str,
    ) -> SupportLLMResponse:  # pragma: no cover - live LLM
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user" if m.role == "customer" else "assistant", "content": m.text}
                for m in conversation.messages
                if m.role != "system"
            ],
        )
        # The agent loop ignores tool_calls/confidence from this adapter
        # until the prompt-to-structured-output contract is wired in
        # M1-CS-02 (next ticket).
        body = "".join(b.text for b in msg.content if hasattr(b, "text"))
        return SupportLLMResponse(reply_text=body, confidence=1.0)


__all__ = [
    "AnthropicSupport",
    "StubSupportLLM",
    "SupportLLM",
    "SupportLLMResponse",
    "ToolCall",
    "SYSTEM_PROMPT_TEMPLATE",
]

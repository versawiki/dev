"""Escalation behaviour tests."""

from __future__ import annotations

from versawiki_support.agent import SupportAgent
from versawiki_support.conversation import Conversation
from versawiki_support.escalation.queue import EscalationQueue
from versawiki_support.escalation.notify import StubNotifier
from versawiki_support.llm import StubSupportLLM, SupportLLMResponse


def test_refund_request_escalates(
    agent: SupportAgent,
    stub_llm: StubSupportLLM,
    tmp_queue: EscalationQueue,
    stub_notifier: StubNotifier,
) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text=(
                "Refunds are handled by a teammate. I've passed your "
                "request along; you'll hear back within 24 hours."
            ),
            confidence=0.9,
            escalate=True,
            escalation_reason="refund request",
            escalation_severity="medium",
        )
    )
    conv = Conversation(tenant_id="t1", customer_identifier="cust@example.com")
    response = agent.handle_customer_text(conv, "I want a refund for last month")
    assert response.escalated is True
    assert conv.status == "escalated"
    assert "refund" in (response.escalation_reason or "").lower()

    # The agent NEVER says "yes" to refunds
    assert "refund issued" not in response.reply_text.lower()
    assert "refunded" not in response.reply_text.lower()

    # Persisted to queue
    entries = tmp_queue.list_all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.conversation_id == conv.id
    assert entry.severity == "medium"
    assert entry.tenant_id == "t1"
    assert entry.customer_identifier == "cust@example.com"
    assert entry.last_messages, "tail of conversation should be snapshotted"

    # Notifier called
    assert len(stub_notifier.sent) == 1
    assert stub_notifier.sent[0].conversation_id == conv.id


def test_low_confidence_escalates_implicitly(
    agent: SupportAgent, stub_llm: StubSupportLLM, tmp_queue: EscalationQueue
) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="I'm not sure about that one.",
            confidence=0.4,
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "obscure edge-case question")
    assert response.escalated is True
    assert response.escalation_reason == "low confidence"
    assert tmp_queue.list_all()[0].severity == "low"


def test_llm_exception_escalates_with_safe_message(
    agent: SupportAgent, stub_llm: StubSupportLLM, tmp_queue: EscalationQueue
) -> None:
    # Force the LLM to raise.
    def boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("upstream down")

    stub_llm.reply = boom  # type: ignore[method-assign]
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "hi")
    assert response.escalated is True
    assert "passed this to a teammate" in response.reply_text.lower() or "teammate" in response.reply_text.lower()
    entries = tmp_queue.list_all()
    assert entries
    assert entries[0].severity == "medium"


def test_explicit_escalate_high_severity_recorded(
    agent: SupportAgent, stub_llm: StubSupportLLM, tmp_queue: EscalationQueue
) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="That sounds like a possible security incident — passing it on.",
            confidence=0.95,
            escalate=True,
            escalation_reason="possible key leak",
            escalation_severity="high",
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(
        conv, "I think my API key leaked, what now?"
    )
    assert response.escalated is True
    assert tmp_queue.list_all()[0].severity == "high"

"""Happy-path: customer asks how to get an API key, agent answers."""

from __future__ import annotations

from versawiki_support.agent import SupportAgent
from versawiki_support.conversation import Conversation
from versawiki_support.llm import StubSupportLLM, SupportLLMResponse


def test_kb_hit_resolves_without_escalation(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text=(
                "You can issue an API key from Settings → API keys. "
                "The raw token shows once; copy it then."
            ),
            confidence=0.95,
        )
    )
    conv = Conversation(tenant_id="t1", customer_identifier="customer@example.com")
    response = agent.handle_customer_text(conv, "How do I get an API key?")
    assert response.escalated is False
    assert conv.status == "resolved_by_agent"
    assert "API key" in response.reply_text
    # KB was searched + matched
    _, kb_matches, _ = stub_llm.calls[-1]
    assert any("api-keys" in a.path.stem for a in kb_matches)


def test_two_message_thread_replays(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(reply_text="Welcome! What do you need?", confidence=0.9)
    )
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Sure — your tenant is on the starter plan.",
            confidence=0.9,
        )
    )
    conv = Conversation(tenant_id="t1")
    agent.handle_customer_text(conv, "hi")
    # First message resolved -> agent reopens on the next message.
    conv.status = "open"
    response = agent.handle_customer_text(conv, "what plan am I on?")
    assert response.escalated is False
    # Conversation now has: cust1, agent1, cust2, agent2
    assert len(conv.messages) == 4
    assert conv.messages[0].role == "customer"
    assert conv.messages[1].role == "agent"
    assert conv.messages[2].role == "customer"
    assert conv.messages[3].role == "agent"


def test_conversation_persisted_on_resolve(agent: SupportAgent, stub_llm: StubSupportLLM, tmp_store) -> None:  # type: ignore[no-untyped-def]
    stub_llm.queue(SupportLLMResponse(reply_text="ok", confidence=0.9))
    conv = Conversation(tenant_id="t1")
    agent.handle_customer_text(conv, "hi there")
    loaded = tmp_store.load(conv.id)
    assert loaded is not None
    assert loaded.status == "resolved_by_agent"
    assert len(loaded.messages) == 2


def test_high_confidence_no_explicit_escalate(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Here's how ingestion works...",
            confidence=0.85,
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "how does ingestion work?")
    assert response.escalated is False

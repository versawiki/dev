"""PII redaction tests.

A customer pasting a credit-card number, SSN, or bearer secret must
NOT have those values stored in the conversation log, and the agent
must not echo them back.
"""

from __future__ import annotations

from versawiki_support.agent import SupportAgent
from versawiki_support.conversation import Conversation
from versawiki_support.llm import StubSupportLLM, SupportLLMResponse
from versawiki_support.messages import new_customer_message, redact_pii


def test_redactor_redacts_valid_credit_card() -> None:
    # Standard Visa test number (passes Luhn)
    text, changed = redact_pii("my card is 4111 1111 1111 1111 ok?")
    assert changed
    assert "4111" not in text
    assert "[REDACTED:CC]" in text


def test_redactor_leaves_random_digits_alone() -> None:
    # Not a valid Luhn number, not 13-19 digits in the right shape
    text, changed = redact_pii("error code 12345")
    assert not changed
    assert "12345" in text


def test_redactor_redacts_ssn() -> None:
    text, changed = redact_pii("ssn is 123-45-6789")
    assert changed
    assert "123-45-6789" not in text
    assert "[REDACTED:SSN]" in text


def test_redactor_redacts_vw_token_keeping_prefix() -> None:
    text, changed = redact_pii(
        "my token is vw_abc123def456_supersecrethere123456789"
    )
    assert changed
    assert "supersecret" not in text
    # The prefix is non-secret per the API key model; we preserve it
    # so the customer can still identify which key
    assert "vw_abc123def456_" in text


def test_redactor_redacts_generic_bearer() -> None:
    text, changed = redact_pii("auth: sk_test_abcdef0123456789")
    assert changed
    assert "abcdef0123456789" not in text


def test_message_factory_marks_redacted_flag() -> None:
    m = new_customer_message("card 4111 1111 1111 1111")
    assert m.redacted is True
    assert "4111" not in m.text


def test_message_factory_unchanged_for_safe_text() -> None:
    m = new_customer_message("hello, how do I get an API key?")
    assert m.redacted is False
    assert "API key" in m.text


def test_conversation_log_never_contains_cc_number(
    agent: SupportAgent, stub_llm: StubSupportLLM, tmp_store
) -> None:  # type: ignore[no-untyped-def]
    stub_llm.queue(
        SupportLLMResponse(
            reply_text=(
                "I see you sent a card number — I redacted it for "
                "your safety. We never store card data here. For "
                "billing changes, please use the billing portal."
            ),
            confidence=0.9,
            escalate=True,
            escalation_reason="customer pasted card data",
            escalation_severity="low",
        )
    )
    conv = Conversation(tenant_id="t1")
    cc = "4111 1111 1111 1111"
    agent.handle_customer_text(conv, f"please update my card to {cc}")
    loaded = tmp_store.load(conv.id)
    assert loaded is not None
    for msg in loaded.messages:
        assert "4111 1111 1111 1111" not in msg.text
        assert "4111111111111111" not in msg.text


def test_agent_reply_does_not_echo_cc(
    agent: SupportAgent, stub_llm: StubSupportLLM
) -> None:
    # Even if the LLM stub tries to echo it, the agent's reply path
    # never receives the raw number — the customer message was
    # redacted before the LLM was called.
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="I see your card; I won't repeat it.",
            confidence=0.9,
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "card 4111 1111 1111 1111")
    assert "4111" not in response.reply_text
    # Confirm what the LLM saw was already redacted
    seen_conv, _, _ = stub_llm.calls[-1]
    assert "4111" not in seen_conv.messages[-1].text

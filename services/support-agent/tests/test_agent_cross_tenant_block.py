"""Cross-tenant block test — load-bearing for privacy.

If this test ever silently flips to passing while the agent actually
returns tenant-B data, we have a privacy breach. The assertions are
designed to be specific about what must NOT happen.
"""

from __future__ import annotations

from versawiki_support.agent import SupportAgent
from versawiki_support.conversation import Conversation
from versawiki_support.escalation.queue import EscalationQueue
from versawiki_support.llm import StubSupportLLM, SupportLLMResponse, ToolCall


def test_cross_tenant_lookup_refused_and_audited_not_escalated(
    agent: SupportAgent,
    stub_llm: StubSupportLLM,
    tmp_queue: EscalationQueue,
) -> None:
    # LLM (incorrectly) attempts to look up tenant B for a tenant-A
    # authenticated customer.
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Looking up tenant-b for you...",
            tool_calls=[
                ToolCall(
                    name="lookup_tenant_status",
                    args={"tenant_id": "tenant-b"},
                ),
            ],
            confidence=0.95,
        )
    )

    conv = Conversation(tenant_id="tenant-a", customer_identifier="cust@a.com")
    response = agent.handle_customer_text(
        conv, "what's the status of tenant-b?"
    )

    # Action must have been refused (not allow)
    assert response.actions_executed, "the gate should have run"
    decision = response.actions_executed[0].decision
    assert decision.status == "deny"
    assert "cross-tenant" in decision.reason

    # CRITICAL: result must be None — no tenant-B data leaked
    assert response.actions_executed[0].result is None

    # CRITICAL: the agent's reply must NOT include any tenant-B-shaped data
    assert "tenant-b" not in response.reply_text.lower() or "cannot" in response.reply_text.lower() or "can't" in response.reply_text.lower() or "not able" in response.reply_text.lower()

    # Audit log present
    assert any("cross-tenant" in line for line in response.audited)

    # No escalation (escalating would leak the existence of tenant-b
    # to the human reviewer queue keyed to tenant-a's conversation;
    # the privacy spec says: audit silently, do not escalate).
    assert response.escalated is False
    assert tmp_queue.list_all() == []


def test_unauthenticated_lookup_also_denied(
    agent: SupportAgent, stub_llm: StubSupportLLM
) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Looking up...",
            tool_calls=[ToolCall(name="lookup_tenant_status", args={"tenant_id": "anything"})],
            confidence=0.9,
        )
    )
    conv = Conversation(tenant_id=None)  # prospect
    response = agent.handle_customer_text(conv, "tell me about tenant anything")
    decision = response.actions_executed[0].decision
    assert decision.status == "deny"
    assert "not authenticated" in decision.reason
    assert response.actions_executed[0].result is None


def test_same_tenant_lookup_allowed(
    agent: SupportAgent, stub_llm: StubSupportLLM
) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Looking up your tenant...",
            tool_calls=[ToolCall(name="lookup_tenant_status", args={"tenant_id": "tenant-a"})],
            confidence=0.95,
        )
    )
    conv = Conversation(tenant_id="tenant-a")
    response = agent.handle_customer_text(conv, "what's my status?")
    assert response.actions_executed[0].decision.status == "allow"
    assert response.actions_executed[0].result is not None
    assert response.escalated is False

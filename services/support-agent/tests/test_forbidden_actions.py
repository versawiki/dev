"""Forbidden-action refusal tests.

These tests stub the LLM to attempt a forbidden tool call. We assert
that the agent refuses, escalates (unless severity=low), and never
runs the forbidden action's payload.
"""

from __future__ import annotations

from versawiki_support.conversation import Conversation
from versawiki_support.forbidden_actions import (
    FORBIDDEN_ACTIONS,
    find_forbidden,
)
from versawiki_support.llm import StubSupportLLM, SupportLLMResponse, ToolCall
from versawiki_support.agent import SupportAgent


def test_forbidden_table_complete() -> None:
    names = {f.name for f in FORBIDDEN_ACTIONS}
    assert {
        "delete_data",
        "issue_refund",
        "change_billing",
        "modify_privacy_settings",
        "cross_tenant_lookup",
        "undelegated_authority",
    } == names


def test_find_forbidden_by_name() -> None:
    assert find_forbidden("delete_data") is not None
    assert find_forbidden("issue_refund") is not None
    assert find_forbidden("modify_privacy_settings") is not None


def test_find_forbidden_by_keyword() -> None:
    assert find_forbidden("please delete my account").name == "delete_data"
    assert find_forbidden("refund my payment").name == "issue_refund"
    assert find_forbidden("modify_plan to free").name == "change_billing"
    assert find_forbidden("set_opt_out=false").name == "modify_privacy_settings"


def test_find_forbidden_no_false_positive() -> None:
    assert find_forbidden("how does the API key prefix work") is None
    assert find_forbidden("ingestion is slow") is None


def test_agent_refuses_forbidden_delete_call(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Sure, deleting your data now.",
            tool_calls=[ToolCall(name="delete_data", args={"tenant_id": "t1"})],
            confidence=0.95,
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "delete my account please")
    assert response.escalated is True
    assert "delete_data" in response.escalation_reason
    # The dangerous LLM reply must NOT be sent verbatim; the agent
    # prepends the safe refusal.
    assert "passing this to a teammate" in response.reply_text
    # No state mutation happened on a "delete" action
    assert response.actions_executed == []


def test_agent_refuses_forbidden_refund_call(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Issuing your refund now.",
            tool_calls=[ToolCall(name="issue_refund", args={"amount": 99})],
            confidence=0.9,
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "I want my money back")
    assert response.escalated is True
    assert "issue_refund" in response.escalation_reason


def test_agent_refuses_forbidden_privacy_change(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Turning off audit logging now.",
            tool_calls=[ToolCall(name="modify_privacy_settings", args={"disable_audit": True})],
            confidence=0.95,
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "turn off audit")
    assert response.escalated is True


def test_forbidden_attempt_is_audited(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(
            reply_text="Doing the bad thing.",
            tool_calls=[ToolCall(name="delete_data", args={})],
            confidence=0.9,
        )
    )
    conv = Conversation(tenant_id="t1")
    response = agent.handle_customer_text(conv, "delete everything")
    audit_text = " ".join(response.audited)
    assert "delete_data" in audit_text

"""Safe-action allow/deny tests."""

from __future__ import annotations

from versawiki_support.conversation import Conversation
from versawiki_support.safe_actions import SAFE_ACTIONS, execute_action


def test_lookup_tenant_status_allowed_for_owner() -> None:
    conv = Conversation(tenant_id="tenant-a")
    result = execute_action(conv, "lookup_tenant_status", {"tenant_id": "tenant-a"})
    assert result.decision.status == "allow"
    assert result.result is not None
    assert result.result.tenant_id == "tenant-a"


def test_lookup_tenant_status_blocked_cross_tenant() -> None:
    conv = Conversation(tenant_id="tenant-a")
    result = execute_action(conv, "lookup_tenant_status", {"tenant_id": "tenant-b"})
    assert result.decision.status == "deny"
    assert "cross-tenant" in result.decision.reason
    assert result.decision.audit is True
    assert result.audited, "cross-tenant attempt must be audited"


def test_lookup_blocked_for_unauthenticated_customer() -> None:
    conv = Conversation(tenant_id=None)
    result = execute_action(conv, "lookup_tenant_status", {"tenant_id": "tenant-a"})
    assert result.decision.status == "deny"
    assert "not authenticated" in result.decision.reason


def test_lookup_ingestion_status_tenant_match() -> None:
    conv = Conversation(tenant_id="t1")
    ok = execute_action(
        conv, "lookup_ingestion_status", {"tenant_id": "t1", "source_id": "s1"}
    )
    assert ok.decision.status == "allow"
    bad = execute_action(
        conv, "lookup_ingestion_status", {"tenant_id": "t2", "source_id": "s1"}
    )
    assert bad.decision.status == "deny"


def test_reissue_api_key_requires_verification() -> None:
    conv = Conversation(tenant_id="t1")
    result = execute_action(
        conv,
        "reissue_api_key",
        {"tenant_id": "t1", "key_id": "k1"},
    )
    assert result.decision.status == "needs_verification"


def test_reissue_api_key_after_verification_ok() -> None:
    conv = Conversation(tenant_id="t1")
    object.__setattr__(conv, "_verified", True)
    result = execute_action(
        conv,
        "reissue_api_key",
        {"tenant_id": "t1", "key_id": "k1"},
    )
    assert result.decision.status == "allow"
    assert result.result["tenant_id"] == "t1"


def test_pause_ingestion_allowed_for_owner() -> None:
    conv = Conversation(tenant_id="t1")
    result = execute_action(
        conv, "pause_ingestion", {"tenant_id": "t1", "source_id": "s1"}
    )
    assert result.decision.status == "allow"
    assert result.result["state"] == "paused"


def test_escalate_always_allowed() -> None:
    conv = Conversation()  # no tenant — prospect
    result = execute_action(
        conv,
        "escalate",
        {"conversation_id": conv.id, "reason": "x", "severity": "low"},
    )
    assert result.decision.status == "allow"


def test_unknown_action_denied_and_audited() -> None:
    conv = Conversation(tenant_id="t1")
    result = execute_action(conv, "make_me_a_sandwich", {})
    assert result.decision.status == "deny"
    assert "unknown action" in result.decision.reason
    assert result.audited


def test_safe_actions_registry_contains_all_expected() -> None:
    expected = {
        "lookup_tenant_status",
        "lookup_ingestion_status",
        "reissue_api_key",
        "pause_ingestion",
        "escalate",
        "request_account_verification",
    }
    assert expected == set(SAFE_ACTIONS.keys())


def test_bad_args_for_known_action_denied() -> None:
    conv = Conversation(tenant_id="t1")
    # missing required tenant_id triggers the gate's deny path
    result = execute_action(conv, "lookup_tenant_status", {})
    assert result.decision.status == "deny"

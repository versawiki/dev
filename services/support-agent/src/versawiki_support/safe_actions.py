"""Curated allow-list of actions the support agent may take.

Each :class:`SafeAction` carries:

- a ``name`` that the LLM emits to invoke it
- a ``handler`` callable
- a ``check`` callable that returns an :class:`ActionDecision` (allow,
  deny-with-reason, or needs-verification) given the conversation
  context and arguments

The LLM never invokes a handler directly. The agent loop parses a
tool-call dict out of the LLM's structured output, looks up the action
by name in :data:`SAFE_ACTIONS`, runs its ``check``, and only then
calls the handler. Anything not in this dict is a refusal.

Cross-tenant rule: every write/read action that takes a ``tenant_id``
argument is checked against the conversation's
``conversation.tenant_id``. A customer authenticated as tenant A
cannot look up tenant B; the action is denied and the cross-tenant
attempt is audit-logged but NOT escalated (escalating would reveal
that tenant B exists).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .conversation import Conversation


ActionDecisionStatus = Literal["allow", "deny", "needs_verification"]


@dataclass(frozen=True)
class ActionDecision:
    """Outcome of a SafeAction.check() call."""

    status: ActionDecisionStatus
    reason: str = ""
    audit: bool = False  # True => log this attempt as a security event

    @classmethod
    def allow(cls) -> "ActionDecision":
        return cls(status="allow")

    @classmethod
    def deny(cls, reason: str, *, audit: bool = False) -> "ActionDecision":
        return cls(status="deny", reason=reason, audit=audit)

    @classmethod
    def needs_verification(cls, reason: str) -> "ActionDecision":
        return cls(status="needs_verification", reason=reason)


@dataclass(frozen=True)
class SafeAction:
    """An action the agent may take, plus its gate."""

    name: str
    description: str
    is_destructive: bool
    handler: Callable[..., Any]
    check: Callable[[Conversation, dict[str, Any]], ActionDecision]


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def _tenant_match_gate(conv: Conversation, args: dict[str, Any]) -> ActionDecision:
    """Allow only if args.tenant_id == conversation.tenant_id (and one exists)."""
    req_tenant = args.get("tenant_id")
    if not req_tenant:
        return ActionDecision.deny("missing tenant_id")
    if conv.tenant_id is None:
        return ActionDecision.deny(
            "customer not authenticated as a tenant",
            audit=False,
        )
    if req_tenant != conv.tenant_id:
        return ActionDecision.deny(
            "cross-tenant lookup attempt blocked",
            audit=True,
        )
    return ActionDecision.allow()


def _verified_destructive_gate(
    conv: Conversation,
    args: dict[str, Any],
) -> ActionDecision:
    """Tenant-match + require verification token on the conversation."""
    base = _tenant_match_gate(conv, args)
    if base.status != "allow":
        return base
    # The agent stamps ``verified=True`` on the conversation after
    # ``request_account_verification`` runs and the customer responds.
    if not getattr(conv, "_verified", False):
        return ActionDecision.needs_verification(
            "account verification required before destructive action"
        )
    return ActionDecision.allow()


def _always_allow(_conv: Conversation, _args: dict[str, Any]) -> ActionDecision:
    return ActionDecision.allow()


# ---------------------------------------------------------------------------
# Handlers (stubs — real wiring lives in the agent runtime;
# tests use the StubSupportLLM + monkeypatching where needed).
# ---------------------------------------------------------------------------

@dataclass
class TenantStatus:
    tenant_id: str
    slug: str
    plan: str
    is_active: bool


@dataclass
class IngestionStatus:
    tenant_id: str
    source_id: str
    state: str  # idle, running, paused, errored
    last_run_at: str | None
    files_indexed: int


def _stub_lookup_tenant_status(tenant_id: str) -> TenantStatus:
    return TenantStatus(
        tenant_id=tenant_id,
        slug=f"slug-{tenant_id[:6]}",
        plan="starter",
        is_active=True,
    )


def _stub_lookup_ingestion_status(tenant_id: str, source_id: str) -> IngestionStatus:
    return IngestionStatus(
        tenant_id=tenant_id,
        source_id=source_id,
        state="idle",
        last_run_at=None,
        files_indexed=0,
    )


def _stub_reissue_api_key(tenant_id: str, key_id: str) -> dict[str, str]:
    # In production, would call POST /v1/admin/tenants/<tenant_id>/api-keys
    # then DELETE /v1/admin/api-keys/<key_id>. The raw token is shown to
    # the customer here; we DO NOT log it.
    return {
        "tenant_id": tenant_id,
        "old_key_id": key_id,
        "new_prefix": "abc123def456",
        "raw_token_emitted_to_customer": "yes",
    }


def _stub_pause_ingestion(tenant_id: str, source_id: str) -> dict[str, str]:
    return {"tenant_id": tenant_id, "source_id": source_id, "state": "paused"}


def _stub_escalate(conversation_id: str, reason: str, severity: str) -> dict[str, str]:
    return {
        "conversation_id": conversation_id,
        "reason": reason,
        "severity": severity,
        "queued": "true",
    }


def _stub_request_account_verification(conversation_id: str) -> dict[str, str]:
    return {"conversation_id": conversation_id, "verification_sent": "true"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SAFE_ACTIONS: dict[str, SafeAction] = {
    "lookup_tenant_status": SafeAction(
        name="lookup_tenant_status",
        description=(
            "Read-only lookup of the customer's tenant status (plan, "
            "active flag). Tenant-scoped."
        ),
        is_destructive=False,
        handler=_stub_lookup_tenant_status,
        check=_tenant_match_gate,
    ),
    "lookup_ingestion_status": SafeAction(
        name="lookup_ingestion_status",
        description=(
            "Read-only lookup of an ingestion source's current state. "
            "Tenant-scoped."
        ),
        is_destructive=False,
        handler=_stub_lookup_ingestion_status,
        check=_tenant_match_gate,
    ),
    "reissue_api_key": SafeAction(
        name="reissue_api_key",
        description=(
            "Reissue an API key the customer owns. Revokes the old key "
            "and returns the raw new token exactly once to the customer."
        ),
        is_destructive=True,
        handler=_stub_reissue_api_key,
        check=_verified_destructive_gate,
    ),
    "pause_ingestion": SafeAction(
        name="pause_ingestion",
        description=(
            "Pause a running ingestion source. Reversible — pausing does "
            "not delete anything."
        ),
        is_destructive=False,
        handler=_stub_pause_ingestion,
        check=_tenant_match_gate,
    ),
    "escalate": SafeAction(
        name="escalate",
        description=(
            "Hand the conversation to a human reviewer. Always allowed."
        ),
        is_destructive=False,
        handler=_stub_escalate,
        check=_always_allow,
    ),
    "request_account_verification": SafeAction(
        name="request_account_verification",
        description=(
            "Send an account verification challenge to the customer. "
            "Gate for any destructive action."
        ),
        is_destructive=False,
        handler=_stub_request_account_verification,
        check=_always_allow,
    ),
}


@dataclass
class ActionExecution:
    """The outcome of attempting one tool call."""

    name: str
    decision: ActionDecision
    result: Any = None
    audited: list[str] = field(default_factory=list)


def execute_action(
    conv: Conversation,
    name: str,
    args: dict[str, Any],
) -> ActionExecution:
    """Look up the action, run its gate, then call the handler.

    Unknown action names are denied (this is the agent's safety net
    against the LLM hallucinating a tool name).
    """
    action = SAFE_ACTIONS.get(name)
    if action is None:
        return ActionExecution(
            name=name,
            decision=ActionDecision.deny(
                f"unknown action {name!r}",
                audit=True,
            ),
            audited=[f"unknown action {name!r}"],
        )
    decision = action.check(conv, args)
    audited: list[str] = []
    if decision.audit:
        audited.append(f"audit: {action.name} denied for conv={conv.id}: {decision.reason}")
    if decision.status != "allow":
        return ActionExecution(name=name, decision=decision, audited=audited)
    try:
        result = action.handler(**args)
    except TypeError as exc:
        return ActionExecution(
            name=name,
            decision=ActionDecision.deny(f"bad arguments: {exc}"),
            audited=audited,
        )
    return ActionExecution(name=name, decision=decision, result=result, audited=audited)


__all__ = [
    "ActionDecision",
    "ActionDecisionStatus",
    "ActionExecution",
    "SafeAction",
    "SAFE_ACTIONS",
    "execute_action",
]

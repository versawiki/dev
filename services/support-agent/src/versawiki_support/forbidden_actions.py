"""Hard-NO action list.

These are not just "not currently in the allow-list" — they are
explicit, named refusals. If the LLM tries to call one (or describes
itself as doing one), the agent refuses, persists an
:class:`AttemptedForbiddenAction` audit record, and escalates with
severity proportional to the attempt.

The names here intentionally cover the cases the LLM might mint on its
own. The check is a name OR substring match against an intent string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ForbiddenSeverity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ForbiddenAction:
    """One hard-NO entry."""

    name: str
    description: str
    keywords: tuple[str, ...]
    severity: ForbiddenSeverity


FORBIDDEN_ACTIONS: tuple[ForbiddenAction, ...] = (
    ForbiddenAction(
        name="delete_data",
        description=(
            "Deleting any customer data (tenant, source, document, key) "
            "is reserved for Josh and the future destructive-action API."
        ),
        keywords=("delete", "drop", "purge", "wipe", "remove_account"),
        severity="high",
    ),
    ForbiddenAction(
        name="issue_refund",
        description="Issuing refunds or credits is finance-only.",
        keywords=("refund", "credit_back", "chargeback_reverse"),
        severity="medium",
    ),
    ForbiddenAction(
        name="change_billing",
        description="Modifying billing plans, payment methods, or invoices.",
        keywords=("change_billing", "update_card", "modify_plan", "downgrade_plan"),
        severity="medium",
    ),
    ForbiddenAction(
        name="modify_privacy_settings",
        description=(
            "Changing the opt-out flag, retention policy, or any "
            "privacy boundary requires explicit human signoff."
        ),
        keywords=(
            "modify_privacy",
            "set_opt_out",
            "set_retention",
            "disable_audit",
            "disable_redaction",
        ),
        severity="high",
    ),
    ForbiddenAction(
        name="cross_tenant_lookup",
        description=(
            "Revealing one customer's info to another. The safe-actions "
            "gate also blocks this; this entry catches LLM intents that "
            "describe it in natural language."
        ),
        keywords=("cross_tenant", "other_tenant", "look_up_another"),
        severity="high",
    ),
    ForbiddenAction(
        name="undelegated_authority",
        description=(
            "Anything the agent has no pre-delegated authority for. "
            "Default refusal."
        ),
        keywords=(
            "sign_contract",
            "promise_sla",
            "agree_to_nda",
            "commit_roadmap",
        ),
        severity="medium",
    ),
)


def find_forbidden(intent: str) -> ForbiddenAction | None:
    """Return the first ForbiddenAction matching the intent string.

    ``intent`` is the action name and/or natural-language description.
    Match is case-insensitive substring against the entry's ``name``
    and each ``keyword``.
    """
    lowered = intent.lower()
    for entry in FORBIDDEN_ACTIONS:
        if entry.name in lowered:
            return entry
        for kw in entry.keywords:
            if kw in lowered:
                return entry
    return None


__all__ = ["ForbiddenAction", "ForbiddenSeverity", "FORBIDDEN_ACTIONS", "find_forbidden"]

"""Pydantic models for skill drafts and on-disk skill records.

The vocabulary types here mirror the discipline that `schema.observation`
applies to `DomainObservation`s: a fixed `Literal` for domain, a fixed
`Literal` for kind, a constrained regex for the title. Anything that
escapes those bounds is *by construction* the wrong shape.

Privacy posture: these models are the **input** to the privacy check
(the markdown body goes through the `CheckerPipeline` before any file is
written). They are intentionally permissive about `body_markdown`
contents at construction time — the checker does the real gate. But the
identifier fields (`domain`, `kind`, `title`) are locked here so they
can be safely embedded in file paths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Fixed vocabularies (bounded — see DECISIONS 2026-05-22 #2)
# ---------------------------------------------------------------------------


# v1 domains. Adding a member is MINOR; removing or renaming is MAJOR.
SkillDomain = Literal[
    "AEC",
    "LegalContracts",
    "ResearchPapers",
    "MedicalRecords",
    "FinancialReports",
    "Other",
]


# v1 skill kinds. Mirrors the bands of `DomainObservation` payloads.
SkillKind = Literal[
    "ingestion-pattern",
    "ontology-shape",
    "naming-convention",
    "relationship-schema",
    "procedure-pattern",
    "query-pattern",
    "classifier-strategy",
]


# Title regex: starts with uppercase, alphanumeric + space + hyphen, 4-81 chars.
TITLE_REGEX = r"^[A-Z][a-zA-Z0-9 -]{3,80}$"


def slugify_title(title: str) -> str:
    """Title -> filename-safe slug.

    Lowercases, replaces spaces/underscores with hyphens, strips anything
    not [a-z0-9-], collapses repeated hyphens. The title regex already
    constrains the input set; the slug is the on-disk identity of the
    skill and any drift here would let a poison title escape into the
    filesystem.
    """

    lowered = title.lower()
    out_chars: list[str] = []
    last_hyphen = False
    for ch in lowered:
        if ch.isalnum():
            out_chars.append(ch)
            last_hyphen = False
        elif ch in (" ", "-", "_"):
            if not last_hyphen:
                out_chars.append("-")
                last_hyphen = True
    slug = "".join(out_chars).strip("-")
    return slug or "untitled"


class SkillDraft(BaseModel):
    """A candidate skill produced by the LLM writer, before privacy check.

    Construction-time invariants: domain and kind are `Literal`s; title
    matches the constrained regex; version is positive; observation ids
    are non-empty (a skill that wasn't derived from observations isn't a
    learned skill). `body_markdown` is unrestricted at this layer — the
    privacy gate runs on it next.

    Note: we DO NOT set `str_strip_whitespace=True` at this layer because
    that would mutate `body_markdown` before the checker hashes it, which
    would desynchronise the rejection-record's `payload_hash` from the
    actual on-disk bytes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: SkillDomain
    kind: SkillKind
    title: str = Field(pattern=TITLE_REGEX, min_length=4, max_length=81)
    body_markdown: str = Field(min_length=1, max_length=64_000)
    derived_from_observation_ids: list[str] = Field(min_length=1, max_length=10_000)
    version: int = Field(ge=1, le=10_000)


class SkillRecord(BaseModel):
    """A skill that has passed the privacy gate and been written to disk.

    The `relative_path` is anchored at `services/meta-mcp/skills/` and
    contains only domain/kind/slugified-title/version — no tenant info,
    no observation-specific identifiers. The `body_sha256` is the sha256
    of the markdown body so callers can verify on-disk content has not
    drifted from what passed the check.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: SkillDomain
    kind: SkillKind
    title: str = Field(pattern=TITLE_REGEX, min_length=4, max_length=81)
    version: int = Field(ge=1, le=10_000)
    relative_path: str = Field(min_length=1, max_length=512)
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_from_observation_ids: list[str] = Field(min_length=1, max_length=10_000)
    written_at_utc: datetime


class SkillRejectionRecord(BaseModel):
    """An audit-log entry for a skill draft the checker rejected.

    Privacy invariant: this record carries ONLY the payload hash and the
    reason. The offending body is never written. Mirrors the discipline
    of `audit.tenant_audit_log.TenantAuditLog` for envelopes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Reason code is a free string here (not the envelope-checker
    # ReasonCode enum) because skill text checks may report shape
    # mismatches the envelope checker doesn't have an enum value for.
    # Constrained to upper-snake-case to keep dashboards tidy.
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    stage: str = Field(min_length=1, max_length=64)
    domain: SkillDomain
    kind: SkillKind
    rejected_at_utc: datetime

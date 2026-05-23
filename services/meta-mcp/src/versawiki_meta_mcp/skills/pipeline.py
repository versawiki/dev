"""`SkillWritingPipeline` — aggregator -> LLM -> CheckerPipeline gate -> disk.

State machine for one skill-writing run:

    meta_store
        |
        v
   [aggregator]  -- per-(domain,kind) groups
        |
        v
   [threshold filter]  -- only groups that cross all three thresholds
        |
        v
   [LLM writer]  -- markdown body for the candidate skill
        |
        v
   [SkillDraft build]  -- enforces title regex + version + bounds
        |
        v
   [CheckerPipeline gate on body_markdown]  <-- LOAD-BEARING PRIVACY GATE
        |                                       no file is written ahead of this
        |   pass                                fail
        v                                       v
   [write file + emit SkillRecord]      [SkillRejectionRecord -> audit log]

Hard invariants (the privacy posture this whole ticket is about):

  1. The on-disk skill file is written ONLY on a `chain.passed=True`
     verdict. There is no other code path here that calls `Path.write_text`.
  2. The audit-log rejection record contains ONLY `payload_hash`,
     `reason_code`, `stage`, and metadata about the *group* the draft
     came from — never the LLM body bytes. This is enforced by
     `SkillRejectionRecord`'s Pydantic shape.
  3. Versioning is monotonic: if `(domain, kind, title)` already exists
     on disk, the new file is written at `v<n+1>`. Old versions are
     preserved for audit.

The pipeline does NOT commit to git — that's `SkillGitCommitter`'s job
and is wired in by the orchestrator. We keep the two separated so a
no-git environment (tests) can exercise the privacy logic without
shelling out.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from ..checkers.results import ChainResult, ReasonCode, Stage
from .aggregator import SignatureAggregator, SignatureGroup
from .base import (
    SkillDomain,
    SkillDraft,
    SkillKind,
    SkillRecord,
    SkillRejectionRecord,
    slugify_title,
)
from .llm_writer import LLMSkillWriter
from .skill_text_check import check_skill_text


_logger = logging.getLogger(__name__)


class SkillWritingOutcome(str, Enum):
    """Per-group outcome of the skill-writing pass."""

    WRITTEN = "written"
    BELOW_THRESHOLD = "below_threshold"
    DRAFT_INVALID = "draft_invalid"   # SkillDraft construction failed (title etc.)
    CHECKER_REJECTED = "checker_rejected"
    SKIPPED_UNCHANGED = "skipped_unchanged"  # identical body already on disk


@dataclass(frozen=True)
class SkillWritingResult:
    """One group's verdict."""

    outcome: SkillWritingOutcome
    group: SignatureGroup
    # Set on WRITTEN.
    record: Optional[SkillRecord] = None
    # Set on CHECKER_REJECTED / DRAFT_INVALID.
    rejection: Optional[SkillRejectionRecord] = None
    chain_result: Optional[ChainResult] = None


# ---------------------------------------------------------------------------
# Audit log writer for rejections.
# ---------------------------------------------------------------------------


class SkillRejectionAuditLog:
    """JSONL writer for skill-draft rejection records.

    Mirrors `audit.tenant_audit_log.TenantAuditLog`'s privacy invariant:
    only `payload_hash + reason_code + stage + timestamp + (domain, kind)`
    ever land on disk. The proposed body itself is NEVER written.

    Lives at `services/meta-mcp/skills/_rejections.jsonl` by default —
    that is a global audit log, not per-domain, because rejection
    metadata isn't tied to a tenant.
    """

    def __init__(self, audit_path: Path) -> None:
        self._path = Path(audit_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: SkillRejectionRecord) -> None:
        payload = record.model_dump(mode="json")
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True))
            f.write("\n")
            f.flush()


# ---------------------------------------------------------------------------
# Title synthesis from the group's shape signal.
# ---------------------------------------------------------------------------


def _title_for_group(group: SignatureGroup) -> str:
    """Synthesize a stable, deterministic title from group properties.

    Output matches `TITLE_REGEX`:
      `^[A-Z][a-zA-Z0-9 -]{3,80}$`

    We DELIBERATELY don't ask the LLM for titles — titles end up in file
    paths, and free-text from an LLM is the wrong shape for a path
    component. Synthesizing keeps the path surface bound to controlled
    inputs.
    """

    # Domain initial-cap is already correct (e.g. "AEC", "LegalContracts").
    # Kind comes in as "ingestion-pattern" etc.; title-case each segment.
    kind_human = " ".join(seg.capitalize() for seg in group.kind.split("-"))
    title = f"{group.domain} {kind_human}"
    # Strip any non-allowed characters defensively, collapse double spaces.
    title = re.sub(r"[^A-Za-z0-9 -]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    # Enforce the regex's length window: title must be at least 4 chars
    # and start with uppercase. Domain starts with uppercase by virtue of
    # the Literal alphabet. If somehow too short, pad with the kind.
    if len(title) < 4:
        title = (title + " Pattern").strip()
    if len(title) > 81:
        title = title[:81].rstrip()
    return title


# ---------------------------------------------------------------------------
# File path layout under the skills root.
# ---------------------------------------------------------------------------


def skill_file_relpath(domain: SkillDomain, kind: SkillKind, title: str, version: int) -> str:
    """Return the on-disk relative path for a skill file.

    Layout: `<domain>/<kind>__<title-slug>__v<n>.md`. POSIX separators.
    No tenant info, no observation-id, no LLM-controlled string.
    """

    slug = slugify_title(title)
    return f"{domain}/{kind}__{slug}__v{version}.md"


def _next_version(skills_root: Path, domain: SkillDomain, kind: SkillKind, title: str) -> int:
    """Find the next free version number for `(domain, kind, title)`."""

    slug = slugify_title(title)
    dir_ = skills_root / domain
    if not dir_.exists():
        return 1
    pattern = re.compile(rf"^{re.escape(kind)}__{re.escape(slug)}__v(\d+)\.md$")
    highest = 0
    for entry in dir_.iterdir():
        if not entry.is_file():
            continue
        m = pattern.match(entry.name)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class SkillWritingPipeline:
    """Aggregator -> LLM -> CheckerPipeline -> disk. All-or-nothing per group."""

    def __init__(
        self,
        *,
        aggregator: SignatureAggregator,
        llm_writer: LLMSkillWriter,
        skills_root: Path,
        rejections_log: Optional[SkillRejectionAuditLog] = None,
    ) -> None:
        self._aggregator = aggregator
        self._llm_writer = llm_writer
        self._skills_root = Path(skills_root)
        self._skills_root.mkdir(parents=True, exist_ok=True)
        self._rejections_log = rejections_log or SkillRejectionAuditLog(
            self._skills_root / "_rejections.jsonl"
        )

    async def run(self) -> list[SkillWritingResult]:
        """Run one full pass. Returns one result per crossing group."""

        crossing = await self._aggregator.compute_threshold_crossing_groups()
        results: list[SkillWritingResult] = []
        for group in crossing:
            results.append(self._process_group(group))
        return results

    # ------------------------------------------------------------------
    # Per-group state machine
    # ------------------------------------------------------------------

    def _process_group(self, group: SignatureGroup) -> SkillWritingResult:
        # --- LLM call. ---
        body_markdown = self._llm_writer.write(group)

        # --- Compute title + tentative version (load-bearing for the path). ---
        title = _title_for_group(group)
        version = _next_version(self._skills_root, group.domain, group.kind, title)

        # --- Build SkillDraft. ---
        try:
            draft = SkillDraft(
                domain=group.domain,
                kind=group.kind,
                title=title,
                body_markdown=body_markdown,
                derived_from_observation_ids=group.observation_ids,
                version=version,
            )
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError or similar
            payload_hash = hashlib.sha256(body_markdown.encode("utf-8")).hexdigest()
            rejection = SkillRejectionRecord(
                payload_hash=payload_hash,
                reason_code="DRAFT_INVALID",
                stage=Stage.SCHEMA_VALIDATE.value,
                domain=group.domain,
                kind=group.kind,
                rejected_at_utc=datetime.now(timezone.utc),
            )
            self._rejections_log.write(rejection)
            _logger.warning(
                "skill writer: draft invalid",
                extra={
                    "payload_hash": payload_hash,
                    "exc_type": type(exc).__name__,
                    "domain": group.domain,
                    "kind": group.kind,
                },
            )
            return SkillWritingResult(
                outcome=SkillWritingOutcome.DRAFT_INVALID,
                group=group,
                rejection=rejection,
            )

        # --- LOAD-BEARING PRIVACY GATE. ---
        # The checker runs on the body BEFORE any file is written.
        chain = check_skill_text(draft.body_markdown)

        if not chain.passed:
            rejection = SkillRejectionRecord(
                payload_hash=chain.payload_hash,
                reason_code=(
                    chain.failed_reason.value
                    if chain.failed_reason is not None
                    else "UNKNOWN_REASON"
                ),
                stage=(
                    chain.failed_stage.value
                    if chain.failed_stage is not None
                    else "unknown_stage"
                ),
                domain=group.domain,
                kind=group.kind,
                rejected_at_utc=datetime.now(timezone.utc),
            )
            self._rejections_log.write(rejection)
            _logger.info(
                "skill writer: checker rejected",
                extra={
                    "payload_hash": chain.payload_hash,
                    "stage": chain.failed_stage.value if chain.failed_stage else None,
                    "reason": chain.failed_reason.value if chain.failed_reason else None,
                    "domain": group.domain,
                    "kind": group.kind,
                },
            )
            return SkillWritingResult(
                outcome=SkillWritingOutcome.CHECKER_REJECTED,
                group=group,
                rejection=rejection,
                chain_result=chain,
            )

        # --- Write to disk. ---
        relpath = skill_file_relpath(draft.domain, draft.kind, draft.title, draft.version)
        absolute = self._skills_root / relpath
        absolute.parent.mkdir(parents=True, exist_ok=True)
        # `x` mode: refuse to clobber an existing file. The version
        # logic above guarantees a fresh path; if it doesn't, we'd
        # rather fail loud than silently overwrite history.
        with open(absolute, "x", encoding="utf-8") as f:
            f.write(draft.body_markdown)

        record = SkillRecord(
            domain=draft.domain,
            kind=draft.kind,
            title=draft.title,
            version=draft.version,
            relative_path=relpath,
            body_sha256=hashlib.sha256(draft.body_markdown.encode("utf-8")).hexdigest(),
            derived_from_observation_ids=draft.derived_from_observation_ids,
            written_at_utc=datetime.now(timezone.utc),
        )
        _logger.info(
            "skill writer: wrote skill",
            extra={"path": relpath, "domain": draft.domain, "kind": draft.kind},
        )
        return SkillWritingResult(
            outcome=SkillWritingOutcome.WRITTEN,
            group=group,
            record=record,
            chain_result=chain,
        )

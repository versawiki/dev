"""`SkillLibraryLoader` — read the on-disk skill tree, index by (domain, kind).

The writer (M1-MCP-03 / `skills/pipeline.py`) lays files out as:

    <skills_root>/<domain>/<kind>__<title-slug>__v<n>.md

The loader walks that tree, parses each file into a `LoadedSkill`
(SkillRecord + body string), and indexes by `(domain, kind)` plus by
domain alone. It reloads only when the tree's mtime changes — so the
hot path of `applier.apply()` doesn't re-stat every file on every call.

Privacy posture: this surface only reads from disk. It NEVER writes.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..skills.base import (
    SkillDomain,
    SkillKind,
    SkillRecord,
    slugify_title,
)


_logger = logging.getLogger(__name__)


# Matches the on-disk filename layout from `skills.pipeline.skill_file_relpath`:
#   `<kind>__<title-slug>__v<n>.md`
# `kind` includes hyphens (e.g. `ingestion-pattern`), so we anchor on the
# `__v\d+\.md$` tail and split from there.
_FILENAME_RE = re.compile(r"^(?P<kind>[a-z][a-z0-9-]*)__(?P<slug>[a-z0-9-]+)__v(?P<version>\d+)\.md$")


# v1 SkillDomain literal members. We can't import the Literal directly as a
# runtime tuple, so we mirror it. If the literal grows, this list must too —
# `test_skill_loader.py` exercises one of these as a guard.
_KNOWN_DOMAINS: tuple[SkillDomain, ...] = (
    "AEC",
    "LegalContracts",
    "ResearchPapers",
    "MedicalRecords",
    "FinancialReports",
    "Other",
)


# v1 SkillKind literal members. Same caveat as `_KNOWN_DOMAINS`.
_KNOWN_KINDS: tuple[SkillKind, ...] = (
    "ingestion-pattern",
    "ontology-shape",
    "naming-convention",
    "relationship-schema",
    "procedure-pattern",
    "query-pattern",
    "classifier-strategy",
)


@dataclass(frozen=True)
class LoadedSkill:
    """One on-disk skill — a `SkillRecord` plus its raw body text.

    The `body_markdown` here is the text the applier prepends to a prompt.
    Kept separately from the `SkillRecord` (which carries only a sha256)
    so the in-memory shape matches the on-disk truth without re-reading
    on every call.
    """

    record: SkillRecord
    body_markdown: str


def _slug_to_title(slug: str) -> str:
    """Reverse `slugify_title` heuristically for display.

    Slugs lose case and word boundaries; we can't recover the original
    title perfectly. But the title we synthesise here only feeds the
    `--- LEARNED PATTERN: <title> ---` separator in the prepended text,
    and the rendered title satisfies the `TITLE_REGEX` regex.
    """

    words = [w for w in slug.split("-") if w]
    if not words:
        return "Untitled"
    # Title-case each word; the regex permits `[A-Z][a-zA-Z0-9 -]{3,80}`
    # which means an all-lowercase camelCase title would fail. Title-casing
    # forces the leading uppercase.
    titled = " ".join(w.capitalize() for w in words)
    # Constrain to the regex's 4-81 char window.
    if len(titled) < 4:
        titled = (titled + " Skill").strip()
    if len(titled) > 81:
        titled = titled[:81].rstrip()
    return titled


def _parse_skill_file(
    path: Path, *, domain: SkillDomain
) -> Optional[LoadedSkill]:
    """Parse one on-disk file into a `LoadedSkill`, or None on shape mismatch.

    Any file that doesn't match the writer's naming layout is skipped —
    we don't want a stray `README.md` or `_rejections.jsonl` to crash
    the loader.
    """

    m = _FILENAME_RE.match(path.name)
    if not m:
        return None
    kind_str = m.group("kind")
    slug = m.group("slug")
    version = int(m.group("version"))

    if kind_str not in _KNOWN_KINDS:
        _logger.warning(
            "applier loader: unknown kind in filename; skipping",
            extra={"path": str(path), "kind": kind_str},
        )
        return None
    kind: SkillKind = kind_str  # type: ignore[assignment]

    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        _logger.warning(
            "applier loader: cannot read skill file; skipping",
            extra={"path": str(path), "exc": str(exc)},
        )
        return None

    title = _slug_to_title(slug)
    # Defensive: the title we round-tripped through a slug must still
    # slugify back to the same slug; if not, the SkillRecord's title and
    # the on-disk filename would disagree.
    if slugify_title(title) != slug:
        _logger.warning(
            "applier loader: title slug round-trip mismatch; skipping",
            extra={"path": str(path), "slug": slug, "derived_title": title},
        )
        return None

    body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    try:
        record = SkillRecord(
            domain=domain,
            kind=kind,
            title=title,
            version=version,
            relative_path=f"{domain}/{path.name}",
            body_sha256=body_sha256,
            # The on-disk file doesn't carry the observation-ids list (those
            # live only in the audit log). For applier purposes we need a
            # non-empty list to satisfy the Pydantic shape; a single
            # placeholder string is principle-only.
            derived_from_observation_ids=["on-disk"],
            written_at_utc=datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ),
        )
    except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError or similar
        _logger.warning(
            "applier loader: SkillRecord construction failed; skipping",
            extra={"path": str(path), "exc": str(exc)},
        )
        return None

    return LoadedSkill(record=record, body_markdown=body)


class SkillLibraryLoader:
    """Walks `services/meta-mcp/skills/` and indexes loaded skills.

    `index_by_domain[domain]` — every skill in that domain.
    `index_by_domain_kind[(domain, kind)]` — narrower index for matchers
    that need to look up by both axes.

    Reload semantics. The loader watches the *latest* mtime across the
    skills root (recursively, files only). When that watermark changes,
    the next call to `load()` reloads the whole tree. We deliberately do
    NOT watch individual files for modification — replacement-by-rename
    + new-version-write (the writer's only two mutations) both bump some
    file's mtime, and a single watermark is enough to trigger a reload.
    """

    def __init__(self, skills_root: Path) -> None:
        self._skills_root = Path(skills_root)
        self._cached_watermark: Optional[float] = None
        self._cached_by_domain: dict[SkillDomain, list[LoadedSkill]] = {}
        self._cached_by_domain_kind: dict[
            tuple[SkillDomain, SkillKind], list[LoadedSkill]
        ] = {}

    @property
    def skills_root(self) -> Path:
        return self._skills_root

    # ------------------------------------------------------------------
    # Mtime watermark
    # ------------------------------------------------------------------

    def _compute_watermark(self) -> float:
        """Latest mtime across all *.md files in the skills tree.

        Returns 0.0 when the tree doesn't exist or is empty. Caller treats
        a change in this value as the reload trigger.
        """

        if not self._skills_root.exists():
            return 0.0
        highest = 0.0
        for entry in self._skills_root.rglob("*.md"):
            if not entry.is_file():
                continue
            try:
                m = entry.stat().st_mtime
            except OSError:
                continue
            if m > highest:
                highest = m
        # Also factor in the directories' own mtimes so a fresh empty
        # `<domain>/` directory (e.g. when the first skill is removed)
        # still moves the watermark.
        for entry in self._skills_root.rglob("*"):
            if not entry.is_dir():
                continue
            try:
                m = entry.stat().st_mtime
            except OSError:
                continue
            if m > highest:
                highest = m
        return highest

    # ------------------------------------------------------------------
    # Loader
    # ------------------------------------------------------------------

    def load(self, *, force: bool = False) -> None:
        """Load (or reload) the on-disk skill tree if mtime has changed.

        `force=True` reloads unconditionally — used by tests and the
        applier's cache-invalidation hook to make state explicit.
        """

        current = self._compute_watermark()
        if not force and self._cached_watermark is not None and current == self._cached_watermark:
            return

        by_domain: dict[SkillDomain, list[LoadedSkill]] = {}
        by_domain_kind: dict[tuple[SkillDomain, SkillKind], list[LoadedSkill]] = {}

        if self._skills_root.exists():
            for domain in _KNOWN_DOMAINS:
                domain_dir = self._skills_root / domain
                if not domain_dir.exists() or not domain_dir.is_dir():
                    continue
                for entry in sorted(domain_dir.iterdir()):
                    if not entry.is_file():
                        continue
                    if not entry.name.endswith(".md"):
                        continue
                    loaded = _parse_skill_file(entry, domain=domain)
                    if loaded is None:
                        continue
                    by_domain.setdefault(domain, []).append(loaded)
                    by_domain_kind.setdefault(
                        (domain, loaded.record.kind), []
                    ).append(loaded)

        self._cached_by_domain = by_domain
        self._cached_by_domain_kind = by_domain_kind
        self._cached_watermark = current

    # ------------------------------------------------------------------
    # Read accessors
    # ------------------------------------------------------------------

    @property
    def watermark(self) -> Optional[float]:
        """The mtime watermark of the most recent load() call (or None)."""

        return self._cached_watermark

    def skills_for_domain(self, domain: SkillDomain) -> list[LoadedSkill]:
        """All loaded skills for `domain`. Triggers a lazy reload if stale."""

        self.load()
        return list(self._cached_by_domain.get(domain, ()))

    def skills_for_domain_kind(
        self, domain: SkillDomain, kind: SkillKind
    ) -> list[LoadedSkill]:
        """Loaded skills narrowed to one `(domain, kind)`."""

        self.load()
        return list(self._cached_by_domain_kind.get((domain, kind), ()))

    def all_skills(self) -> list[LoadedSkill]:
        """Every loaded skill across all domains."""

        self.load()
        out: list[LoadedSkill] = []
        for skills in self._cached_by_domain.values():
            out.extend(skills)
        return out

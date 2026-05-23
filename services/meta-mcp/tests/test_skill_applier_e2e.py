"""SkillApplier end-to-end: synthetic skill library + tenant config -> applied text."""

from __future__ import annotations

import asyncio
from pathlib import Path

from versawiki_meta_mcp.applier.applier import SkillApplier
from versawiki_meta_mcp.applier.prompt_injector import (
    APPLIED_TEXT_END_MARKER,
    APPLIED_TEXT_SEPARATOR_PREFIX,
)
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig


_TENANT_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


def _run(awaitable):
    return asyncio.run(awaitable)


def _seed_full_aec_skill_tree(root: Path) -> None:
    """A two-skill AEC library, both clearly applicable to an AEC tenant."""

    aec = root / "AEC"
    aec.mkdir(parents=True, exist_ok=True)
    (aec / "ingestion-pattern__aec-doc-types__v1.md").write_text(
        "Pattern: AEC corpora are dominated by drawing, specification, "
        "rfi, submittal, and meeting_minutes types. Prioritise "
        "drawing+rfi disambiguation in the classifier.\n",
        encoding="utf-8",
    )
    (aec / "naming-convention__aec-drawing-naming__v1.md").write_text(
        "Naming: AEC drawing numbers carry phase, discipline, and "
        "sequence tokens.\nTemplate <phase>-<discipline>-<sequence>.\n",
        encoding="utf-8",
    )


def _aec_tenant_config() -> TenantSignatureConfig:
    return TenantSignatureConfig(
        tenant_anon_id=_TENANT_ID,
        type_vocab={
            "Drawing": "drawing",
            "Spec": "specification",
            "RFI": "rfi",
            "Submittal": "submittal",
            "MeetingMinutes": "meeting_minutes",
        },
        naming_token_vocab={
            "Phase": "phase",
            "Discipline": "discipline",
            "Sequence": "sequence",
        },
    )


def test_e2e_returns_applied_text_in_expected_format(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _seed_full_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root)

    text = _run(applier.apply("tenant-A", _aec_tenant_config(), "classifier"))
    assert text is not None

    # Stable separator format the ingestion service's prompts.py pattern-
    # matches on.
    assert text.startswith(APPLIED_TEXT_SEPARATOR_PREFIX)
    assert text.rstrip().endswith(APPLIED_TEXT_END_MARKER)

    # Both fixture skills should be present (both score above the floor).
    assert "AEC corpora" in text
    assert "Naming:" in text

    # Multi-skill output: the END->blank-line->LEARNED PATTERN transition.
    assert (
        APPLIED_TEXT_END_MARKER + "\n\n" + APPLIED_TEXT_SEPARATOR_PREFIX
    ) in text


def test_e2e_returns_none_when_no_matches(tmp_path: Path) -> None:
    """A tenant whose vocab is empty -> no overlap signal, no kind-bonus."""

    root = tmp_path / "skills"
    _seed_full_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root)

    barren = TenantSignatureConfig(
        tenant_anon_id=_TENANT_ID,
        # No vocab maps at all -> no overlap signal, no kind-bonus.
    )
    text = _run(applier.apply("tenant-Z", barren, "classifier"))
    # With no vocab signal the matcher score sits below the default 0.4 floor.
    assert text is None


def test_e2e_returns_none_for_empty_library(tmp_path: Path) -> None:
    root = tmp_path / "skills_empty"
    root.mkdir(parents=True, exist_ok=True)
    applier = SkillApplier(skills_root=root)
    text = _run(applier.apply("tenant-A", _aec_tenant_config(), "classifier"))
    assert text is None


def test_e2e_kind_narrowing(tmp_path: Path) -> None:
    """Requesting a specific kind narrows the output to that kind only."""

    root = tmp_path / "skills"
    _seed_full_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root)

    naming_only = _run(
        applier.apply(
            "tenant-A",
            _aec_tenant_config(),
            "ingestion-pattern",
            kind="naming-convention",
        )
    )
    assert naming_only is not None
    assert "Naming:" in naming_only
    assert "AEC corpora" not in naming_only

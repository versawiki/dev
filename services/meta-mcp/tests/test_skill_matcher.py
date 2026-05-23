"""SkillMatcher: matching AEC tenant config against AEC skill fixtures."""

from __future__ import annotations

from pathlib import Path

from versawiki_meta_mcp.applier.loader import SkillLibraryLoader
from versawiki_meta_mcp.applier.matcher import SkillMatcher
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig


_TENANT_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


def _make_aec_skill_tree(root: Path) -> None:
    """A small fixture skill library referencing AEC vocab members.

    The bodies deliberately mention controlled-vocabulary members
    (`drawing`, `rfi`, `phase`, `discipline`) — that's what the matcher
    scores against.
    """

    root.mkdir(parents=True, exist_ok=True)
    aec = root / "AEC"
    aec.mkdir(parents=True, exist_ok=True)
    (aec / "ingestion-pattern__aec-doc-types__v1.md").write_text(
        "Pattern: AEC corpora are dominated by drawing, specification, "
        "rfi, submittal, and meeting_minutes types. The classifier should "
        "prioritise drawing+rfi disambiguation.\n",
        encoding="utf-8",
    )
    (aec / "naming-convention__aec-drawing-naming__v1.md").write_text(
        "Naming: AEC drawings carry phase, discipline, sequence tokens.\n"
        "Template: <phase>-<discipline>-<sequence>.\n",
        encoding="utf-8",
    )
    legal = root / "LegalContracts"
    legal.mkdir(parents=True, exist_ok=True)
    (legal / "ingestion-pattern__legal-contracts__v1.md").write_text(
        "Pattern: contract corpora are dominated by contract and "
        "correspondence types.\n",
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
        relation_type_vocab={"Drawing": "drawing", "RFI": "rfi"},
    )


def _non_aec_tenant_config() -> TenantSignatureConfig:
    """A tenant whose vocab values never appear in the AEC skill bodies."""

    return TenantSignatureConfig(
        tenant_anon_id=_TENANT_ID,
        # Use only `other` and `image`/`spreadsheet`/`presentation` which
        # the AEC fixture bodies don't mention.
        type_vocab={"Random": "other", "Pic": "image", "Slides": "presentation"},
    )


def test_matches_aec_tenant_against_aec_skills(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _make_aec_skill_tree(root)

    loader = SkillLibraryLoader(root)
    matcher = SkillMatcher(loader)
    matches = matcher.match("AEC", _aec_tenant_config())

    assert len(matches) == 2
    # All AEC-only results.
    assert all(m.skill.record.domain == "AEC" for m in matches)
    # Scores ordered descending.
    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)
    # Top match should be well above the default min_score floor.
    assert matches[0].score >= 0.4


def test_no_match_for_unrelated_tenant(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _make_aec_skill_tree(root)

    loader = SkillLibraryLoader(root)
    matcher = SkillMatcher(loader)
    matches = matcher.match("AEC", _non_aec_tenant_config())

    # Skills are returned (the matcher doesn't apply the floor) but their
    # scores should be substantially lower than a matching tenant's.
    # The "non-aec" tenant has no AEC vocab so vocab_jaccard and
    # doc_type_jaccard should both be 0.
    for m in matches:
        # The base domain weight floor + kind-bonus contribution at most.
        # Both AEC kinds here have a kind bonus matching `type_vocab` or
        # `naming_token_vocab` -- the latter is empty on this tenant.
        assert m.score < 0.5


def test_kind_filter_narrows_results(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _make_aec_skill_tree(root)

    loader = SkillLibraryLoader(root)
    matcher = SkillMatcher(loader)
    matches = matcher.match("AEC", _aec_tenant_config(), kind="naming-convention")
    assert len(matches) == 1
    assert matches[0].skill.record.kind == "naming-convention"


def test_other_domain_skills_never_match(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _make_aec_skill_tree(root)

    loader = SkillLibraryLoader(root)
    matcher = SkillMatcher(loader)
    # An AEC-domain query never returns LegalContracts entries.
    matches = matcher.match("AEC", _aec_tenant_config())
    for m in matches:
        assert m.skill.record.domain == "AEC"

"""Taxonomy loader + heuristic match_score sanity tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from versawiki_ingestion.classification.taxonomy import Taxonomy, TaxonomyType
from versawiki_ingestion.parsers.base import ParseResult


def _parsed(full_text: str, fields: dict | None = None) -> ParseResult:
    return ParseResult(
        document_type="general_document",
        full_text=full_text,
        fields=fields or {},
        confidence=0.5,
    )


def test_starter_loads_aec_seed_with_known_types() -> None:
    t = Taxonomy.starter()
    names = set(t.type_names())
    # Some well-known AEC seed types must be present.
    for required in ("contract", "rfi", "submittal", "drawing", "meeting_minutes"):
        assert required in names, f"{required} missing from starter taxonomy"
    # Catch-alls are injected by the loader even though they live under
    # `settings` in the YAML.
    assert "general_document" in names
    assert "unclassified" in names


def test_list_types_and_get_type() -> None:
    t = Taxonomy.starter()
    types = t.list_types()
    assert types
    assert all(isinstance(x, TaxonomyType) for x in types)
    rfi = t.get_type("rfi")
    assert rfi is not None
    assert rfi.name == "rfi"
    assert t.get_type("does-not-exist") is None


def test_match_score_zero_for_unknown_type() -> None:
    t = Taxonomy.starter()
    assert t.match_score(_parsed("hello"), "totally_made_up") == 0.0


def test_match_score_zero_when_text_is_unrelated() -> None:
    t = Taxonomy.starter()
    score = t.match_score(_parsed("the quick brown fox"), "rfi")
    # Some incidental token overlap is possible (e.g. "rfi" appearing nowhere
    # but other field keywords might leak in). Should still be very low.
    assert score < 0.2


def test_match_score_high_when_filename_pattern_hits_and_text_matches() -> None:
    t = Taxonomy.starter()
    text = (
        "RFI-042 — Question about conduit routing. submitted_by: Jane. "
        "assigned_to: structural team. response: pending."
    )
    score = t.match_score(_parsed(text, fields={"title": "RFI 042"}), "rfi", source_uri="docs/rfi_042.pdf")
    assert score >= 0.6
    assert score <= 1.0


def test_best_match_picks_rfi_for_rfi_like_doc() -> None:
    t = Taxonomy.starter()
    text = "RFI submitted by acme; question about concrete mix design. response pending."
    name, score = t.best_match(_parsed(text), source_uri="job/rfi_log.txt")
    assert name == "rfi"
    assert score > 0.0


def test_best_match_falls_back_to_default_when_all_zero() -> None:
    t = Taxonomy.starter()
    name, score = t.best_match(_parsed(""), source_uri="")
    assert score == 0.0
    assert name == t.default_type


def test_score_all_returns_one_per_type() -> None:
    t = Taxonomy.starter()
    scores = t.score_all(_parsed("just some text"))
    assert set(scores.keys()) == set(t.type_names())
    assert all(0.0 <= s <= 1.0 for s in scores.values())


def test_with_overrides_adds_and_replaces_types() -> None:
    t = Taxonomy.starter()
    # Add a brand-new type and override the description of an existing one.
    overrides = {
        "permit": {
            "display_name": "Building Permit",
            "description": "Permits issued by an authority having jurisdiction.",
            "file_patterns": ["*permit*"],
        },
        "rfi": {
            "display_name": "RFI (custom)",
            "description": "Tenant-overridden RFI description.",
            "file_patterns": ["*rfi*"],
        },
    }
    t2 = t.with_overrides(overrides)
    assert "permit" in t2
    assert t2.get_type("rfi").display_name == "RFI (custom)"  # type: ignore[union-attr]
    # Original is untouched.
    assert t.get_type("rfi").display_name != "RFI (custom)"  # type: ignore[union-attr]


def test_from_yaml_handles_minimal_doc(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tiny.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            document_types:
              foo:
                display_name: Foo
                description: A test type.
                file_patterns: ["*foo*"]
            settings:
              default_type: foo
              unclassified_type: unclassified
            """
        ).strip(),
        encoding="utf-8",
    )
    t = Taxonomy.from_yaml(yaml_path)
    assert "foo" in t
    # default_type was injected even though we already had foo; it should
    # also exist by name.
    assert "unclassified" in t


def test_empty_taxonomy_raises() -> None:
    with pytest.raises(ValueError):
        Taxonomy([])


def test_filename_pattern_alone_is_partial_score() -> None:
    t = Taxonomy.starter()
    # Generic text with only a filename hint.
    score = t.match_score(_parsed("nothing relevant"), "contract", source_uri="acme_contract_v1.pdf")
    # Pattern hit gives 0.4 baseline.
    assert score >= 0.4

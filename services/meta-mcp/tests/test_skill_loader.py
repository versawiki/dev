"""SkillLibraryLoader: reads fixture tree, indexes by (domain, kind), reloads on mtime."""

from __future__ import annotations

import os
import time
from pathlib import Path

from versawiki_meta_mcp.applier.loader import SkillLibraryLoader


def _write(path: Path, body: str) -> None:
    """Write a file with explicit mtime bump so the watermark visibly moves."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _bump_mtime(path: Path) -> None:
    """Touch a file to a strictly-future mtime, bypassing FS clock resolution."""

    now = time.time() + 2.0
    os.utime(path, (now, now))


def test_loads_aec_skills_from_fixture_tree(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write(
        root / "AEC" / "ingestion-pattern__aec-ingestion-pattern__v1.md",
        "# AEC ingestion pattern\nReferences drawing and rfi types.\n",
    )
    _write(
        root / "AEC" / "naming-convention__aec-naming-convention__v1.md",
        "# AEC naming\nTemplate <phase>-<discipline>-<sequence>.\n",
    )

    loader = SkillLibraryLoader(root)
    loader.load()
    aec_skills = loader.skills_for_domain("AEC")
    assert len(aec_skills) == 2
    titles = sorted(s.record.title for s in aec_skills)
    assert any("Ingestion" in t for t in titles)
    assert any("Naming" in t for t in titles)


def test_indexes_by_domain_kind(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write(
        root / "AEC" / "ingestion-pattern__aec-stuff__v1.md",
        "body 1",
    )
    _write(
        root / "AEC" / "naming-convention__aec-naming__v1.md",
        "body 2",
    )
    _write(
        root / "LegalContracts" / "ingestion-pattern__legal-ingest__v1.md",
        "body 3",
    )

    loader = SkillLibraryLoader(root)
    loader.load()
    aec_ingest = loader.skills_for_domain_kind("AEC", "ingestion-pattern")
    legal_ingest = loader.skills_for_domain_kind("LegalContracts", "ingestion-pattern")
    aec_naming = loader.skills_for_domain_kind("AEC", "naming-convention")
    assert len(aec_ingest) == 1
    assert len(legal_ingest) == 1
    assert len(aec_naming) == 1
    assert aec_ingest[0].body_markdown == "body 1"


def test_reloads_when_mtime_changes(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    initial = root / "AEC" / "ingestion-pattern__aec-stuff__v1.md"
    _write(initial, "first body")

    loader = SkillLibraryLoader(root)
    loader.load()
    first = loader.skills_for_domain("AEC")
    assert len(first) == 1
    assert first[0].body_markdown == "first body"
    watermark_initial = loader.watermark

    # Add a second skill — moves the watermark.
    second = root / "AEC" / "ingestion-pattern__aec-stuff__v2.md"
    _write(second, "second body")
    _bump_mtime(second)

    # A re-read should pick up the new file.
    loader.load()
    after = loader.skills_for_domain("AEC")
    assert len(after) == 2
    assert loader.watermark != watermark_initial


def test_skips_unrecognised_filenames(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write(root / "AEC" / "ingestion-pattern__aec-stuff__v1.md", "valid")
    _write(root / "AEC" / "_rejections.jsonl", "junk")  # not even .md
    _write(root / "AEC" / "README.md", "stray markdown")
    _write(root / "AEC" / "bad__shape.md", "wrong name layout")

    loader = SkillLibraryLoader(root)
    loader.load()
    skills = loader.skills_for_domain("AEC")
    assert len(skills) == 1
    assert skills[0].body_markdown == "valid"


def test_empty_tree_returns_no_skills(tmp_path: Path) -> None:
    root = tmp_path / "nonexistent"
    loader = SkillLibraryLoader(root)
    loader.load()
    assert loader.skills_for_domain("AEC") == []
    assert loader.all_skills() == []

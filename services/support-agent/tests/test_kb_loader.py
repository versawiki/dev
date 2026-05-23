"""KB loader tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

from versawiki_support.knowledge_base import KnowledgeBase, _parse_frontmatter


def _write_article(root: Path, name: str, body: str, tags: list[str]) -> Path:
    tags_str = "[" + ", ".join(tags) + "]"
    path = root / name
    path.write_text(
        f"---\nname: {name}\ntags: {tags_str}\nlast_reviewed: 2026-05-23\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_frontmatter_parse_basic() -> None:
    raw = "---\nname: foo\ntags: [a, b, c]\nlast_reviewed: 2026-01-01\n---\n\nbody here"
    fm, body = _parse_frontmatter(raw)
    assert fm["name"] == "foo"
    assert fm["tags"] == ["a", "b", "c"]
    assert fm["last_reviewed"] == "2026-01-01"
    assert body.strip() == "body here"


def test_frontmatter_missing_returns_empty() -> None:
    fm, body = _parse_frontmatter("# heading\nno frontmatter here")
    assert fm == {}
    assert body.startswith("# heading")


def test_load_indexes_real_kb() -> None:
    kb_root = Path(__file__).resolve().parents[1] / "kb"
    kb = KnowledgeBase.load(kb_root)
    names = {a.path.stem for a in kb.articles}
    expected = {
        "getting-started",
        "api-keys",
        "ingestion",
        "privacy",
        "billing",
        "troubleshooting",
        "escalation-criteria",
    }
    assert expected.issubset(names)


def test_search_keyword_overlap(tmp_path: Path) -> None:
    _write_article(tmp_path, "alpha.md", "API keys are great.", ["api-keys", "tokens"])
    _write_article(tmp_path, "beta.md", "Ingestion explained.", ["ingestion"])
    kb = KnowledgeBase.load(tmp_path)
    results = kb.search("how do I rotate an API key?")
    assert results, "expected at least one match"
    assert results[0].path.stem == "alpha"


def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    _write_article(tmp_path, "alpha.md", "About widgets.", ["widgets"])
    kb = KnowledgeBase.load(tmp_path)
    assert kb.search("astrophysics") == []


def test_hot_reload_on_mtime(tmp_path: Path) -> None:
    p = _write_article(tmp_path, "foo.md", "first version", ["foo"])
    kb = KnowledgeBase.load(tmp_path)
    assert kb.get("foo") is not None
    assert "first version" in kb.get("foo").body  # type: ignore[union-attr]

    # Force mtime bump (some filesystems have low resolution; sleep + utime)
    time.sleep(0.01)
    p.write_text(
        "---\nname: foo.md\ntags: [foo]\nlast_reviewed: 2026-05-23\n---\n\nsecond version\n",
        encoding="utf-8",
    )
    os.utime(p, None)

    assert kb.maybe_reload() is True
    assert "second version" in kb.get("foo").body  # type: ignore[union-attr]


def test_hot_reload_detects_new_file(tmp_path: Path) -> None:
    _write_article(tmp_path, "a.md", "alpha body", ["alpha"])
    kb = KnowledgeBase.load(tmp_path)
    assert len(kb.articles) == 1
    _write_article(tmp_path, "b.md", "beta body", ["beta"])
    assert kb.maybe_reload() is True
    assert len(kb.articles) == 2


def test_hot_reload_no_change_returns_false(tmp_path: Path) -> None:
    _write_article(tmp_path, "a.md", "body", ["a"])
    kb = KnowledgeBase.load(tmp_path)
    assert kb.maybe_reload() is False

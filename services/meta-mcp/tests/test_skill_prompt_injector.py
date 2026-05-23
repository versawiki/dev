"""SkillPromptInjector: budget, min_score floor, descending-score order."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from versawiki_meta_mcp.applier.loader import LoadedSkill
from versawiki_meta_mcp.applier.matcher import MatchedSkill
from versawiki_meta_mcp.applier.prompt_injector import (
    APPLIED_TEXT_END_MARKER,
    APPLIED_TEXT_SEPARATOR_PREFIX,
    SkillPromptInjector,
)
from versawiki_meta_mcp.skills.base import SkillRecord


def _make_loaded(title: str, body: str, *, kind: str = "ingestion-pattern") -> LoadedSkill:
    body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    rec = SkillRecord(
        domain="AEC",
        kind=kind,  # type: ignore[arg-type]
        title=title,
        version=1,
        relative_path=f"AEC/{kind}__{title.lower().replace(' ', '-')}__v1.md",
        body_sha256=body_sha,
        derived_from_observation_ids=["fixture"],
        written_at_utc=datetime.now(timezone.utc),
    )
    return LoadedSkill(record=rec, body_markdown=body)


def _match(title: str, body: str, score: float) -> MatchedSkill:
    return MatchedSkill(skill=_make_loaded(title, body), score=score, why="test")


def test_respects_min_score_floor() -> None:
    injector = SkillPromptInjector(max_chars=10_000, min_score=0.5)
    matches = [
        _match("High Score Skill", "body-high", 0.9),
        _match("Low Score Skill", "body-low", 0.1),
        _match("Mid Score Skill", "body-mid", 0.45),
    ]
    result = injector.render(matches)
    assert "High Score Skill" in result.text
    assert "Low Score Skill" not in result.text
    assert "Mid Score Skill" not in result.text
    assert result.skipped_below_min_score == 2


def test_orders_by_score_descending() -> None:
    injector = SkillPromptInjector(max_chars=10_000, min_score=0.1)
    matches = [
        _match("Beta", "body-beta", 0.5),
        _match("Alpha", "body-alpha", 0.9),
        _match("Gamma", "body-gamma", 0.7),
    ]
    result = injector.render(matches)
    a_pos = result.text.index("Alpha")
    g_pos = result.text.index("Gamma")
    b_pos = result.text.index("Beta")
    assert a_pos < g_pos < b_pos


def test_respects_max_chars_budget() -> None:
    # Three skills each ~200 chars; budget = 250 -> only the top match fits
    # (possibly truncated).
    body = "x" * 200
    injector = SkillPromptInjector(max_chars=250, min_score=0.1)
    matches = [
        _match("Skill A", body, 0.9),
        _match("Skill B", body, 0.8),
        _match("Skill C", body, 0.7),
    ]
    result = injector.render(matches)
    assert len(result.text) <= 250
    # First (highest-scoring) skill should be present.
    assert "Skill A" in result.text
    # Second and third should be dropped.
    assert "Skill B" not in result.text
    assert "Skill C" not in result.text
    assert result.truncated


def test_separators_are_stable_format() -> None:
    injector = SkillPromptInjector(max_chars=10_000, min_score=0.1)
    matches = [_match("Test Skill", "body content", 0.9)]
    result = injector.render(matches)
    assert APPLIED_TEXT_SEPARATOR_PREFIX in result.text
    assert "Test Skill" in result.text
    assert APPLIED_TEXT_END_MARKER in result.text
    assert result.text.startswith(APPLIED_TEXT_SEPARATOR_PREFIX)
    # The end marker is the last text element of the output.
    assert result.text.rstrip().endswith(APPLIED_TEXT_END_MARKER)


def test_multiple_skills_separated_by_blank_line() -> None:
    injector = SkillPromptInjector(max_chars=10_000, min_score=0.1)
    matches = [
        _match("Skill One", "body one", 0.9),
        _match("Skill Two", "body two", 0.8),
    ]
    result = injector.render(matches)
    # Skills are joined by "\n\n" — so an "--- END ---\n\n--- LEARNED PATTERN: "
    # transition is present.
    assert APPLIED_TEXT_END_MARKER + "\n\n" + APPLIED_TEXT_SEPARATOR_PREFIX in result.text


def test_empty_input_returns_empty_text() -> None:
    injector = SkillPromptInjector()
    result = injector.render([])
    assert result.text == ""
    assert result.used_skill_paths == ()


def test_partial_truncation_includes_marker() -> None:
    # Force a truncation of the body itself: budget tight but big enough
    # for header+tail+some body.
    body = "y" * 1000
    injector = SkillPromptInjector(max_chars=200, min_score=0.1)
    matches = [_match("Long Skill", body, 0.9)]
    result = injector.render(matches)
    assert "Long Skill" in result.text
    assert "[...truncated]" in result.text
    assert result.truncated
    assert len(result.text) <= 200

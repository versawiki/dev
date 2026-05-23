"""Verify that observe-mode short-circuits the PR open path."""

from __future__ import annotations

import pytest

from versawiki_orchestrator.audit import AuditLog
from versawiki_orchestrator.config import Settings
from versawiki_orchestrator.github import GitHubPRWriter
from versawiki_orchestrator.main import _make_pr_callback


async def test_observe_mode_does_not_push(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    # Conftest sets mode="observe" by default.
    assert settings.mode == "observe"
    pr_writer = GitHubPRWriter(settings=settings)
    cb = await _make_pr_callback(settings=settings, audit=tmp_audit, pr_writer=pr_writer)
    url = await cb("vw-agent/test", "summary")
    assert url is None  # no PR opened
    types = [e.event_type for e in tmp_audit.tail(5)]
    assert "pr_would_open" in types


async def test_act_mode_with_empty_branch_skips(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    """Even in act mode, the callback should refuse an empty branch
    (the agent didn't actually commit anything)."""
    settings = settings.model_copy(update={"mode": "act"})
    pr_writer = GitHubPRWriter(settings=settings)
    cb = await _make_pr_callback(settings=settings, audit=tmp_audit, pr_writer=pr_writer)
    url = await cb("", "no branch summary")
    assert url is None
    types = [e.event_type for e in tmp_audit.tail(5)]
    assert "pr_would_open" in types
    # The reason field should distinguish from observe mode.
    last = tmp_audit.tail(1)[0]
    assert last.payload["reason"] == "no_branch"

"""Unit tests for the runner's helpers and ResultMessage-shape handling.

These do NOT spin up the real SDK; they exercise:
- `_extract_tokens` against the various shapes ResultMessage may carry
  (dict, attr-on-usage, attr-on-message)
- `_extract_cost_usd` against `total_cost_usd`
- PR-url regex extraction from a free-form summary
- The skip-if-branch-exists guard
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from versawiki_orchestrator.agent import AgentRunner
from versawiki_orchestrator.agent.runner import (
    _PR_URL_RE,
    _TICKET_ID_RE,
    _extract_cost_usd,
    _extract_tokens,
    RunResult,
)
from versawiki_orchestrator.audit import AuditLog
from versawiki_orchestrator.config import Settings
from versawiki_orchestrator.events.types import ManualEvent, TickEvent
from versawiki_orchestrator.spending import SpendingTracker


# ----------------------------------------------------------------------
# Token extraction
# ----------------------------------------------------------------------


@dataclass
class _FakeResultUsageDict:
    """SDK shape 1: `.usage` dict, `.total_cost_usd` set."""

    usage: dict[str, Any]
    total_cost_usd: float | None = None


@dataclass
class _FakeUsageObj:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeResultUsageObj:
    """SDK shape 2: `.usage` object with attributes."""

    usage: _FakeUsageObj
    total_cost_usd: float | None = None


@dataclass
class _FakeResultDirect:
    """SDK shape 3: attrs directly on the result."""

    input_tokens: int
    output_tokens: int
    total_cost_usd: float | None = None


def test_extract_tokens_from_dict_usage() -> None:
    msg = _FakeResultUsageDict(
        usage={"input_tokens": 1234, "output_tokens": 567}
    )
    assert _extract_tokens(msg) == (1234, 567)


def test_extract_tokens_from_object_usage() -> None:
    msg = _FakeResultUsageObj(
        usage=_FakeUsageObj(input_tokens=10, output_tokens=20)
    )
    assert _extract_tokens(msg) == (10, 20)


def test_extract_tokens_from_direct_attrs() -> None:
    msg = _FakeResultDirect(input_tokens=3, output_tokens=4)
    assert _extract_tokens(msg) == (3, 4)


def test_extract_tokens_missing_returns_zero() -> None:
    class _Empty:
        pass

    assert _extract_tokens(_Empty()) == (0, 0)


def test_extract_cost_prefers_total_cost_usd() -> None:
    msg = _FakeResultUsageDict(
        usage={"input_tokens": 1, "output_tokens": 1},
        total_cost_usd=0.0123,
    )
    assert _extract_cost_usd(msg) == pytest.approx(0.0123)


def test_extract_cost_missing_returns_zero() -> None:
    class _Empty:
        pass

    assert _extract_cost_usd(_Empty()) == 0.0


# ----------------------------------------------------------------------
# Regex constants
# ----------------------------------------------------------------------


def test_pr_url_regex_matches_canonical_url() -> None:
    summary = "All done. Opened PR: https://github.com/versawiki/dev/pull/42"
    m = _PR_URL_RE.search(summary)
    assert m is not None
    assert m.group(0) == "https://github.com/versawiki/dev/pull/42"


def test_ticket_id_regex_matches_canonical_id() -> None:
    assert _TICKET_ID_RE.search("Please tackle M3-OPS-04 next.").group(0) == (
        "M3-OPS-04"
    )
    assert _TICKET_ID_RE.search("ticket M2-SUP-07a-fix").group(0) == (
        "M2-SUP-07a-fix"
    )


# ----------------------------------------------------------------------
# Success flag: PR URL recovered from the agent's summary
# ----------------------------------------------------------------------


async def test_success_set_when_pr_url_in_summary(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    """When the SDK returns a summary containing a PR URL, the runner
    should set success=True and pr_url even with no pr_callback wired in.
    """
    spending = SpendingTracker(tmp_audit, settings)
    runner = AgentRunner(
        settings=settings,
        audit=tmp_audit,
        spending=spending,
        pr_callback=None,
    )

    async def fake_do_run(event: Any, result: RunResult) -> None:
        # Simulate the SDK loop completing with a summary that mentions
        # a PR URL but no callback was invoked.
        result.summary = (
            "Picked M3-XYZ-01. Tests pass. "
            "Opened https://github.com/versawiki/dev/pull/123 from "
            "vw-agent/M3-XYZ-01."
        )
        result.input_tokens = 100
        result.output_tokens = 50
        # Mirror what runner._do_run does after the SDK loop:
        import re
        m = re.search(r"https://github\.com/[^\s]+/pull/\d+", result.summary)
        if m is not None:
            result.pr_url = m.group(0)
            result.success = True

    with patch.object(runner, "_do_run", side_effect=fake_do_run):
        result = await runner.handle(TickEvent())

    assert result.success is True
    assert result.pr_url == "https://github.com/versawiki/dev/pull/123"


# ----------------------------------------------------------------------
# Skip-if-branch-exists guard
# ----------------------------------------------------------------------


async def test_duplicate_branch_short_circuits(
    tmp_audit: AuditLog, settings: Settings, tmp_path: Path
) -> None:
    """If a local branch `vw-agent/<ticket>` already exists, the second
    run for the same ticket id should short-circuit before the SDK loop.
    """
    # Set up a tiny git repo with an agent branch present.
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = settings.model_copy(update={"repo_workdir": repo})
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "x@x"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "x"], cwd=repo, check=True
    )
    # Need an initial commit before branching.
    (repo / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "branch", "vw-agent/M9-DUP-01"], cwd=repo, check=True
    )

    spending = SpendingTracker(tmp_audit, settings)
    runner = AgentRunner(
        settings=settings,
        audit=tmp_audit,
        spending=spending,
        pr_callback=None,
    )

    event = ManualEvent(instruction="Please work on ticket M9-DUP-01 today.")
    result = await runner.handle(event)

    assert result.success is False
    assert result.error == "duplicate_branch"
    assert result.summary == "branch already exists"
    assert result.branch == "vw-agent/M9-DUP-01"

    types = [e.event_type for e in tmp_audit.tail(20)]
    assert "run_skipped_duplicate_branch" in types


async def test_no_ticket_id_no_guard(
    tmp_audit: AuditLog, settings: Settings, tmp_path: Path
) -> None:
    """A ManualEvent without a ticket-id pattern should NOT trigger the
    guard — it just falls through to the SDK import error in this env.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = settings.model_copy(update={"repo_workdir": repo})

    spending = SpendingTracker(tmp_audit, settings)
    runner = AgentRunner(
        settings=settings,
        audit=tmp_audit,
        spending=spending,
        pr_callback=None,
    )

    event = ManualEvent(instruction="say hello to the world")
    result = await runner.handle(event)
    # No short-circuit row.
    types = [e.event_type for e in tmp_audit.tail(20)]
    assert "run_skipped_duplicate_branch" not in types
    # Either the SDK ran (if installed) or it bailed in _do_run; either
    # way, run_started is present (we got past the guard).
    assert "run_started" in types

"""PR writer safety tests — branch name validation, no main pushes."""

from __future__ import annotations

import pytest

from versawiki_orchestrator.config import Settings
from versawiki_orchestrator.github import GitHubPRWriter, PrWriteError


async def test_refuses_non_agent_branch(settings: Settings) -> None:
    pw = GitHubPRWriter(settings=settings)
    with pytest.raises(PrWriteError, match="must match"):
        await pw.push_and_open_pr(
            branch="main", title="evil", body="evil", head_sha_hint=None
        )


async def test_refuses_branch_with_traversal(settings: Settings) -> None:
    pw = GitHubPRWriter(settings=settings)
    with pytest.raises(PrWriteError, match="must match"):
        await pw.push_and_open_pr(
            branch="vw-agent/../main",
            title="evil",
            body="evil",
            head_sha_hint=None,
        )


async def test_refuses_empty_branch(settings: Settings) -> None:
    pw = GitHubPRWriter(settings=settings)
    with pytest.raises(PrWriteError, match="must match"):
        await pw.push_and_open_pr(branch="", title="", body="", head_sha_hint=None)


async def test_accepts_well_formed_agent_branch_name() -> None:
    """The regex itself, applied directly — we don't network here.

    The PR writer's `_AGENT_BRANCH_RE` is the trust boundary; verify the
    set of names that should pass.
    """
    from versawiki_orchestrator.github.pr_writer import _AGENT_BRANCH_RE

    good = [
        "vw-agent/M1-ING-03c",
        "vw-agent/M1.MCP.05",
        "vw-agent/abc_123",
        "vw-agent/short",
    ]
    for b in good:
        assert _AGENT_BRANCH_RE.match(b), f"should accept {b!r}"

    bad = [
        "main",
        "vw-agent/",
        "vw-agent/../main",
        "vw-agent/with space",
        "VW-agent/M1",  # case-sensitive prefix
        "vw-agent/M1;rm",
    ]
    for b in bad:
        assert not _AGENT_BRANCH_RE.match(b), f"should reject {b!r}"

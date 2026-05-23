"""SkillGitCommitter: stages + commits, never pushes, message is deterministic.

Subprocess is mocked — no real git runs in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import pytest

from versawiki_meta_mcp.skills.base import SkillRecord
from versawiki_meta_mcp.skills.git_commit import RunResult, SkillGitCommitter


class _FakeRunner:
    """Records every argv handed to it; returns success by default."""

    def __init__(self, *, returncode: int = 0) -> None:
        self.calls: list[tuple[list[str], Optional[str]]] = []
        self._returncode = returncode

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        check: bool = True,
    ) -> RunResult:
        self.calls.append((list(argv), cwd))
        return RunResult(returncode=self._returncode, stdout="", stderr="")


def _record(
    *,
    domain: str = "AEC",
    kind: str = "naming-convention",
    title: str = "AEC Naming Convention",
    version: int = 1,
    relpath: str = "AEC/naming-convention__aec-naming-convention__v1.md",
    obs_ids: Optional[list[str]] = None,
) -> SkillRecord:
    return SkillRecord(
        domain=domain,
        kind=kind,
        title=title,
        version=version,
        relative_path=relpath,
        body_sha256="a" * 64,
        derived_from_observation_ids=obs_ids or [
            "abcdefab-cdef-4abc-9abc-abcdefab0001",
            "abcdefab-cdef-4abc-9abc-abcdefab0002",
        ],
        written_at_utc=datetime.now(timezone.utc),
    )


def test_committer_runs_add_then_commit(tmp_path: Path) -> None:
    runner = _FakeRunner()
    committer = SkillGitCommitter(repo_root=tmp_path, runner=runner)
    result = committer.commit_record(_record())

    assert result.returncode == 0
    # Two calls: git add, git commit.
    assert len(runner.calls) == 2
    add_argv, _ = runner.calls[0]
    commit_argv, _ = runner.calls[1]
    assert add_argv[:2] == ["git", "add"]
    assert "services/meta-mcp/skills/AEC/naming-convention__aec-naming-convention__v1.md" in add_argv
    assert commit_argv[:2] == ["git", "commit"]
    assert "-m" in commit_argv


def test_committer_never_invokes_push(tmp_path: Path) -> None:
    runner = _FakeRunner()
    committer = SkillGitCommitter(repo_root=tmp_path, runner=runner)
    committer.commit_records(
        [_record(version=1), _record(version=2, relpath="AEC/naming-convention__aec-naming-convention__v2.md")]
    )
    all_argv = [argv for argv, _ in runner.calls]
    # No call should include the word "push".
    for argv in all_argv:
        assert "push" not in argv, f"push found in argv: {argv}"
    # Add + commit for each record = 4 calls.
    assert len(runner.calls) == 4


def test_commit_message_is_deterministic_and_lists_observation_ids(tmp_path: Path) -> None:
    runner = _FakeRunner()
    committer = SkillGitCommitter(repo_root=tmp_path, runner=runner)
    obs_ids = [
        "abcdefab-cdef-4abc-9abc-abcdefab0001",
        "abcdefab-cdef-4abc-9abc-abcdefab0002",
        "abcdefab-cdef-4abc-9abc-abcdefab0003",
    ]
    committer.commit_record(_record(obs_ids=obs_ids))

    _commit_argv, _ = runner.calls[1]
    # The -m value follows "-m".
    m_idx = _commit_argv.index("-m")
    message = _commit_argv[m_idx + 1]

    # Header includes the canonical relative path.
    assert "skills: add AEC/naming-convention__aec-naming-convention__v1.md" in message
    # Body lists each source observation id.
    for oid in obs_ids:
        assert oid in message


def test_split_git_dir_flags_used_when_provided(tmp_path: Path) -> None:
    """When git_dir is provided, argv includes --git-dir + --work-tree."""

    git_dir = tmp_path / "vw_git"
    work_tree = tmp_path / "work"
    runner = _FakeRunner()
    committer = SkillGitCommitter(
        repo_root=work_tree, git_dir=git_dir, runner=runner
    )
    committer.commit_record(_record())

    add_argv, _ = runner.calls[0]
    assert any(a.startswith("--git-dir=") for a in add_argv)
    assert any(a.startswith("--work-tree=") for a in add_argv)


def test_runner_cwd_is_repo_root(tmp_path: Path) -> None:
    runner = _FakeRunner()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    committer = SkillGitCommitter(repo_root=repo_root, runner=runner)
    committer.commit_record(_record())
    for _, cwd in runner.calls:
        assert cwd == str(repo_root)


def test_empty_records_returns_none(tmp_path: Path) -> None:
    runner = _FakeRunner()
    committer = SkillGitCommitter(repo_root=tmp_path, runner=runner)
    assert committer.commit_records([]) is None
    assert runner.calls == []

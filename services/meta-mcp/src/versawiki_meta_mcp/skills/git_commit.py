"""`SkillGitCommitter` — `git add` + `git commit` for newly-written skills.

Does NOT push. Pushing is the team git pipeline's responsibility (see
`AGENTS.md` / `DECISIONS.md` 2026-05-22 — Code lives at github.com/versawiki/dev).

Subprocess injection: tests pass a fake `SubprocessRunner` that records
the argv lists handed to it instead of actually shelling out. The
default uses Python's `subprocess.run`.

Per-commit message format:

    skills: add <domain>/<kind>__<slug>__v<n>

    Derived from observations:
      - <event-id>
      - <event-id>
      ...

The observation event-ids are uuids and pass the static-checker
whitelist; they are safe to record in commit history. The commit message
deliberately does NOT include the body sha256 — the file is already
under version control so its content is captured by the commit's tree
object.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence, runtime_checkable

from .base import SkillRecord


_logger = logging.getLogger(__name__)


@runtime_checkable
class SubprocessRunner(Protocol):
    """Minimal subprocess interface — injectable for tests."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        check: bool = True,
    ) -> "RunResult":
        ...


@dataclass(frozen=True)
class RunResult:
    """Stand-in for `subprocess.CompletedProcess` — small surface."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class _RealSubprocessRunner:
    """Production runner: thin wrapper over `subprocess.run`."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        check: bool = True,
    ) -> RunResult:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )
        return RunResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def _commit_message(record: SkillRecord) -> str:
    """Deterministic commit message — body lists source observation ids."""

    header = f"skills: add {record.relative_path}"
    body_lines = ["Derived from observations:"]
    for obs_id in record.derived_from_observation_ids:
        body_lines.append(f"  - {obs_id}")
    return header + "\n\n" + "\n".join(body_lines) + "\n"


class SkillGitCommitter:
    """Stages and commits newly-written skill files.

    Args:
        repo_root: absolute path to the git work-tree (e.g. the versawiki
            repo root). Used as the cwd for git invocations.
        git_dir: optional override for `GIT_DIR`. In split-git layouts
            (see MEMORY.md note about cowork sandboxes) the git-dir is
            not co-located with the work-tree; pass it here and we
            translate to `--git-dir=...` flags.
        runner: injected `SubprocessRunner` — tests pass a fake.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        git_dir: Optional[Path] = None,
        runner: Optional[SubprocessRunner] = None,
    ) -> None:
        self._repo_root = Path(repo_root)
        self._git_dir = Path(git_dir) if git_dir is not None else None
        self._runner = runner or _RealSubprocessRunner()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def commit_records(self, records: Iterable[SkillRecord]) -> Optional[RunResult]:
        """Stage every record's file and create one commit per record.

        We commit one-skill-per-commit so the audit history reads cleanly
        ("this commit added this skill, derived from these observations").

        Returns the result of the LAST commit (handy for tests). Returns
        `None` if `records` was empty.
        """

        last: Optional[RunResult] = None
        for record in records:
            last = self._commit_one(record)
        return last

    def commit_record(self, record: SkillRecord) -> RunResult:
        """Stage and commit a single record."""

        return self._commit_one(record)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _git_argv(self, *args: str) -> list[str]:
        out = ["git"]
        if self._git_dir is not None:
            out.extend(
                [
                    f"--git-dir={self._git_dir}",
                    f"--work-tree={self._repo_root}",
                ]
            )
        out.extend(args)
        return out

    def _commit_one(self, record: SkillRecord) -> RunResult:
        # The skills dir is at `services/meta-mcp/skills/` per the
        # ticket. Resolve the record's relative_path against that prefix.
        skill_rel = f"services/meta-mcp/skills/{record.relative_path}"

        add_argv = self._git_argv("add", "--", skill_rel)
        add_result = self._runner.run(add_argv, cwd=str(self._repo_root))
        _logger.info(
            "git add",
            extra={"path": skill_rel, "returncode": add_result.returncode},
        )

        message = _commit_message(record)
        commit_argv = self._git_argv("commit", "-m", message, "--", skill_rel)
        commit_result = self._runner.run(commit_argv, cwd=str(self._repo_root))
        _logger.info(
            "git commit",
            extra={"path": skill_rel, "returncode": commit_result.returncode},
        )
        return commit_result

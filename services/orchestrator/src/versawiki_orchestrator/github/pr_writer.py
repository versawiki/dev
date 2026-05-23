"""Branch-only Git push + PR open through the GitHub REST API.

Why hand-rolled rather than PyGithub: keeps the dependency surface small,
the only calls we make are `GET /repos/.../branches/main/protection` and
`POST /repos/.../pulls`. Both are stable v3 endpoints.

Safety:
- Verifies branch protection on `main` at startup. If the configured
  `main` branch is NOT protected, opening a PR is fine but pushing is
  refused — the spec is unambiguous that this orchestrator must never
  have a path to push main.
- Only ever pushes to refs matching `refs/heads/vw-agent/*`. The push
  command itself is namespaced; anything else is rejected before the
  network call.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import subprocess  # noqa: S404 — required to drive git locally
from pathlib import Path
from typing import Any

import httpx
import structlog

from ..config import Settings


_log = structlog.get_logger("versawiki_orchestrator.github")

_GITHUB_API = "https://api.github.com"
_AGENT_BRANCH_RE = re.compile(r"^vw-agent/[A-Za-z0-9._-]+$")


class BranchProtectionError(Exception):
    """Raised when `main` is not adequately protected."""


class PrWriteError(Exception):
    """Raised when we can't open a PR."""


class GitHubPRWriter:
    """Push an agent's branch to origin and open a PR.

    Stateless: each `push_and_open_pr` call drives `git push` in the repo
    workdir, then hits the GitHub API to create the PR.
    """

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Startup checks
    # ------------------------------------------------------------------

    async def verify_main_protection(self) -> dict[str, Any]:
        """Confirm `main` is protected. Raises BranchProtectionError if not.

        We don't mutate protection rules from here — that's a one-time
        manual step Josh runs from the deploy guide. We only verify.
        """
        s = self._settings
        url = (
            f"{_GITHUB_API}/repos/{s.gh_owner}/{s.gh_repo}/branches/"
            f"{s.main_branch}/protection"
        )
        token = s.gh_pat.get_secret_value()
        if not token:
            raise BranchProtectionError(
                "GH_PAT not configured; cannot verify branch protection"
            )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if resp.status_code == 404:
            raise BranchProtectionError(
                f"branch `{s.main_branch}` is not protected on {s.gh_owner}/{s.gh_repo}; "
                "follow the deploy guide to set up protection before flipping ACT mode"
            )
        if resp.status_code != 200:
            raise BranchProtectionError(
                f"unexpected protection check status {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        # Minimal sanity: required PR reviews + status checks must exist.
        reviews = data.get("required_pull_request_reviews") or {}
        checks = data.get("required_status_checks") or {}
        if not reviews:
            raise BranchProtectionError(
                "branch protection missing required_pull_request_reviews — "
                "agent could merge its own PRs"
            )
        if not checks.get("contexts"):
            _log.warning("branch_protection_no_required_status_checks", data=data)
        return data

    # ------------------------------------------------------------------
    # Push + PR
    # ------------------------------------------------------------------

    async def push_and_open_pr(
        self,
        *,
        branch: str,
        title: str,
        body: str,
        head_sha_hint: str | None = None,
    ) -> str:
        """Push `branch` to origin and open a PR. Returns PR HTML URL."""
        if not _AGENT_BRANCH_RE.match(branch):
            raise PrWriteError(
                f"refusing to push branch {branch!r} — must match `vw-agent/<id>`"
            )

        # Push first. Any failure here aborts before we touch the API.
        await self._git_push(branch)

        s = self._settings
        url = f"{_GITHUB_API}/repos/{s.gh_owner}/{s.gh_repo}/pulls"
        token = s.gh_pat.get_secret_value()
        if not token:
            raise PrWriteError("GH_PAT not configured; cannot open PR")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "title": title,
                    "body": body,
                    "head": branch,
                    "base": s.main_branch,
                    "maintainer_can_modify": True,
                    "draft": False,
                },
            )
        if resp.status_code >= 300:
            raise PrWriteError(
                f"PR open failed: status={resp.status_code} body={resp.text[:500]}"
            )
        return str(resp.json().get("html_url") or "")

    # ------------------------------------------------------------------
    # Local git
    # ------------------------------------------------------------------

    async def _git_push(self, branch: str) -> None:
        """Run `git push origin <branch>` in the repo workdir."""
        s = self._settings
        repo = Path(s.repo_workdir)
        if not (repo / ".git").exists() and not (repo.parent / ".git").exists():
            raise PrWriteError(
                f"repo_workdir {repo} is not a git working tree"
            )
        # Use shell-safe args via list-form Popen. No interpolation.
        token = s.gh_pat.get_secret_value()
        remote_url = (
            f"https://x-access-token:{token}@github.com/{s.gh_owner}/{s.gh_repo}.git"
        )
        # Set the origin URL transiently for the push (no on-disk creds).
        env = {"GIT_TERMINAL_PROMPT": "0"}
        cmd = ["git", "push", remote_url, f"refs/heads/{branch}:refs/heads/{branch}"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(repo),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            # Scrub the token from any output before raising.
            scrub = (stderr or stdout or b"").decode("utf-8", errors="replace")
            scrub = scrub.replace(token, "***")
            raise PrWriteError(
                f"git push failed (rc={proc.returncode}): {scrub[:500]}"
            )
        _log.info("agent_branch_pushed", branch=branch)


__all__ = ["GitHubPRWriter", "BranchProtectionError", "PrWriteError"]

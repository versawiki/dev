"""Decide whether one of the orchestrator's own PRs is safe to merge.

We only merge PRs whose head ref looks like one of ours (`vw-agent/*`).
Even then there are multiple guardrails:

  1. The PR body / title must not contain `[needs-review]` — that's
     the marker the agent uses when it bails out unsure.
  2. The PR must touch only "small" amounts of code (configurable
     via `auto_merge_max_files` and `auto_merge_max_lines`).
  3. The PR must not touch any path on the privacy-critical list:
       - `services/meta-mcp/src/versawiki_meta_mcp/checkers/pipeline.py`
       - `services/meta-mcp/src/versawiki_meta_mcp/audit/tenant_audit_log.py`
       - anything under `docs/architecture/`
       - `AGENTS.md`, `DECISIONS.md`
  4. Every check-run on the PR head sha must have `conclusion=success`.
     If any are still pending / in_progress we return `wait`. If any
     have failed we return `block_failed_checks`.

Only when every gate passes do we PUT `/pulls/{n}/merge` with squash.

This module is GitHub-API-only — it does not run `git` locally. That
keeps it side-effect-light and easy to unit-test with respx.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from ..audit import AuditLog
from ..config import Settings


_log = structlog.get_logger("versawiki_orchestrator.auto_merge")

_GITHUB_API = "https://api.github.com"

# `^vw-agent/<id>$` — same shape we accept in the PR writer.
_AGENT_BRANCH_RE = re.compile(r"^vw-agent/[A-Za-z0-9._-]+$")

# Marker the agent inserts in its PR title or body when something
# is weird and a human needs to look at the diff before merge.
_NEEDS_REVIEW_RE = re.compile(r"\[needs-review\]", re.IGNORECASE)


# Files we never auto-merge into. The full list comes from AGENTS.md's
# hard rules; mirrored here so this module doesn't have to read the
# repo to know what's privacy-critical.
PRIVACY_CRITICAL_PATHS: tuple[str, ...] = (
    "services/meta-mcp/src/versawiki_meta_mcp/checkers/pipeline.py",
    "services/meta-mcp/src/versawiki_meta_mcp/audit/tenant_audit_log.py",
    "AGENTS.md",
    "DECISIONS.md",
)

# Directory prefixes we never auto-merge into.
PRIVACY_CRITICAL_PREFIXES: tuple[str, ...] = (
    "docs/architecture/",
)


@dataclass
class MergeDecision:
    """The outcome of evaluating one PR."""

    pr_number: int
    merged: bool
    reason: str
    summary: str
    # The commit sha that was (or would have been) merged. None if we
    # never got that far (e.g. the head ref didn't match).
    head_sha: str | None = None


def _file_is_privacy_critical(path: str) -> bool:
    if path in PRIVACY_CRITICAL_PATHS:
        return True
    for prefix in PRIVACY_CRITICAL_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class AutoMerger:
    """Stateless. One per orchestrator process; reusable across PRs."""

    def __init__(
        self,
        *,
        settings: Settings,
        audit: AuditLog,
        run_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._audit = audit
        # `run_id` is the orchestrator process ID / boot id, included
        # in the merge commit message so we can trace it later. Optional
        # so callers that don't care can omit it.
        self._run_id = run_id or "unknown"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate_and_merge(self, pr_number: int) -> MergeDecision:
        """Evaluate PR `pr_number`. Merge if safe, else return why not.

        Never raises. Network errors are caught and reported as a
        decision with `merged=False` so the caller's polling loop
        can carry on.
        """
        try:
            return await self._evaluate_and_merge(pr_number)
        except httpx.HTTPError as exc:  # network glitches happen
            _log.warning("auto_merge_http_error", pr=pr_number, error=str(exc))
            return MergeDecision(
                pr_number=pr_number,
                merged=False,
                reason="http_error",
                summary=f"network error talking to GitHub: {exc}",
            )

    # ------------------------------------------------------------------
    # Inner logic
    # ------------------------------------------------------------------

    async def _evaluate_and_merge(self, pr_number: int) -> MergeDecision:
        s = self._settings
        token = s.gh_pat.get_secret_value()
        if not token:
            return MergeDecision(
                pr_number=pr_number,
                merged=False,
                reason="no_token",
                summary="GH_PAT not configured; cannot auto-merge",
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        owner, repo = s.gh_owner, s.gh_repo
        pr_url = f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            pr_resp = await client.get(pr_url, headers=headers)
            if pr_resp.status_code != 200:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="pr_fetch_failed",
                    summary=(
                        f"GET pull/{pr_number} returned "
                        f"{pr_resp.status_code}: {pr_resp.text[:200]}"
                    ),
                )
            pr = pr_resp.json()

            # Gate 1: head ref must be one of ours.
            head_ref = (pr.get("head") or {}).get("ref") or ""
            if not _AGENT_BRANCH_RE.match(head_ref):
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="head_ref_not_agent",
                    summary=f"head ref {head_ref!r} is not an agent branch",
                    head_sha=(pr.get("head") or {}).get("sha"),
                )

            head_sha = (pr.get("head") or {}).get("sha") or ""

            # Gate 2: [needs-review] marker.
            title = pr.get("title") or ""
            body = pr.get("body") or ""
            if _NEEDS_REVIEW_RE.search(title) or _NEEDS_REVIEW_RE.search(body):
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="needs_review",
                    summary="PR is marked [needs-review]; human must look",
                    head_sha=head_sha,
                )

            # Gate 3: size caps.
            changed_files = int(pr.get("changed_files") or 0)
            additions = int(pr.get("additions") or 0)
            deletions = int(pr.get("deletions") or 0)
            total_lines = additions + deletions
            if changed_files > s.auto_merge_max_files:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="too_many_files",
                    summary=(
                        f"PR touches {changed_files} files "
                        f"(cap {s.auto_merge_max_files})"
                    ),
                    head_sha=head_sha,
                )
            if total_lines > s.auto_merge_max_lines:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="too_many_lines",
                    summary=(
                        f"PR touches {total_lines} lines "
                        f"(cap {s.auto_merge_max_lines})"
                    ),
                    head_sha=head_sha,
                )

            # Gate 4: privacy-critical file list.
            files_url = (
                f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"
            )
            files_resp = await client.get(
                files_url,
                headers=headers,
                params={"per_page": "100"},
            )
            if files_resp.status_code != 200:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="files_fetch_failed",
                    summary=(
                        f"GET files returned {files_resp.status_code}: "
                        f"{files_resp.text[:200]}"
                    ),
                    head_sha=head_sha,
                )
            files = files_resp.json()
            critical_hits: list[str] = []
            for f in files:
                path = f.get("filename") or ""
                if _file_is_privacy_critical(path):
                    critical_hits.append(path)
            if critical_hits:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="privacy_critical_path",
                    summary=(
                        "PR touches privacy-critical paths: "
                        + ", ".join(critical_hits)
                    ),
                    head_sha=head_sha,
                )

            # Gate 5: check-runs on the head sha.
            checks_url = (
                f"{_GITHUB_API}/repos/{owner}/{repo}/commits/"
                f"{head_sha}/check-runs"
            )
            checks_resp = await client.get(
                checks_url,
                headers=headers,
                params={"per_page": "100"},
            )
            if checks_resp.status_code != 200:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="checks_fetch_failed",
                    summary=(
                        f"GET check-runs returned {checks_resp.status_code}: "
                        f"{checks_resp.text[:200]}"
                    ),
                    head_sha=head_sha,
                )
            check_runs = (checks_resp.json() or {}).get("check_runs") or []
            if not check_runs:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="no_checks",
                    summary="no check-runs reported yet; will retry next cycle",
                    head_sha=head_sha,
                )

            pending = []
            failed = []
            for run in check_runs:
                status = run.get("status") or ""
                conclusion = run.get("conclusion") or ""
                name = run.get("name") or "?"
                if status in ("queued", "in_progress", "pending"):
                    pending.append(name)
                    continue
                # status=completed past this point
                if conclusion == "success":
                    continue
                if conclusion in ("neutral", "skipped"):
                    # Neutral / skipped don't block — treat as success.
                    continue
                # failure, cancelled, timed_out, action_required, stale
                failed.append(f"{name}={conclusion}")

            if pending:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="wait",
                    summary=(
                        f"{len(pending)} check(s) still running: "
                        + ", ".join(pending[:5])
                    ),
                    head_sha=head_sha,
                )
            if failed:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=False,
                    reason="block_failed_checks",
                    summary=(
                        f"{len(failed)} check(s) failed: "
                        + ", ".join(failed[:5])
                    ),
                    head_sha=head_sha,
                )

            # All gates passed — squash-merge.
            merge_url = f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/merge"
            merge_body = {
                "merge_method": "squash",
                "commit_title": f"{title} (#{pr_number})",
                "commit_message": (
                    "Auto-merged by versawiki-orchestrator.\n\n"
                    f"orchestrator_run_id: {self._run_id}\n"
                    f"head_sha: {head_sha}\n"
                    f"head_ref: {head_ref}\n"
                ),
            }
            merge_resp = await client.put(
                merge_url, headers=headers, json=merge_body
            )
            if merge_resp.status_code == 200:
                return MergeDecision(
                    pr_number=pr_number,
                    merged=True,
                    reason="merged",
                    summary=(
                        f"squash-merged {head_sha[:8]} from {head_ref} "
                        f"({changed_files} files, {total_lines} lines)"
                    ),
                    head_sha=head_sha,
                )
            return MergeDecision(
                pr_number=pr_number,
                merged=False,
                reason="merge_api_failed",
                summary=(
                    f"PUT merge returned {merge_resp.status_code}: "
                    f"{merge_resp.text[:200]}"
                ),
                head_sha=head_sha,
            )

    # ------------------------------------------------------------------
    # List-open helper (used by the background poller in main.py)
    # ------------------------------------------------------------------

    async def list_open_agent_prs(self) -> list[int]:
        """Return PR numbers of open PRs whose head ref starts with `vw-agent/`."""
        s = self._settings
        token = s.gh_pat.get_secret_value()
        if not token:
            return []
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        url = f"{_GITHUB_API}/repos/{s.gh_owner}/{s.gh_repo}/pulls"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                headers=headers,
                params={"state": "open", "per_page": "100"},
            )
        if resp.status_code != 200:
            _log.warning(
                "list_open_prs_failed",
                status=resp.status_code,
                body=resp.text[:200],
            )
            return []
        out: list[int] = []
        for pr in resp.json() or []:
            head_ref = (pr.get("head") or {}).get("ref") or ""
            if _AGENT_BRANCH_RE.match(head_ref):
                out.append(int(pr.get("number")))
        return out

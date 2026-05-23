"""AutoMerger unit tests.

We mock the GitHub API with respx so each test exercises one gate.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from versawiki_orchestrator.audit import AuditLog
from versawiki_orchestrator.auto_merge import AutoMerger, MergeDecision
from versawiki_orchestrator.config import Settings


_API = "https://api.github.com"


def _pr_payload(
    *,
    number: int = 7,
    head_ref: str = "vw-agent/M1-TEST-01",
    head_sha: str = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    title: str = "agent: a small change",
    body: str = "summary",
    changed_files: int = 2,
    additions: int = 10,
    deletions: int = 4,
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "body": body,
        "changed_files": changed_files,
        "additions": additions,
        "deletions": deletions,
        "head": {"ref": head_ref, "sha": head_sha},
    }


def _files_payload(filenames: list[str]) -> list[dict[str, Any]]:
    return [{"filename": f} for f in filenames]


def _checks_payload(
    runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if runs is None:
        runs = [
            {
                "name": "test (orchestrator)",
                "status": "completed",
                "conclusion": "success",
            }
        ]
    return {"check_runs": runs}


def _build_merger(
    settings: Settings, audit: AuditLog, run_id: str = "test-run"
) -> AutoMerger:
    return AutoMerger(settings=settings, audit=audit, run_id=run_id)


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


@respx.mock
async def test_happy_path_squash_merges(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(200, json=_pr_payload())
    )
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7/files").mock(
        return_value=httpx.Response(
            200, json=_files_payload(["services/api/src/foo.py", "README.md"])
        )
    )
    respx.get(
        f"{_API}/repos/versawiki/dev/commits/"
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef/check-runs"
    ).mock(return_value=httpx.Response(200, json=_checks_payload()))
    merge_route = respx.put(f"{_API}/repos/versawiki/dev/pulls/7/merge").mock(
        return_value=httpx.Response(
            200, json={"merged": True, "sha": "newsha"}
        )
    )

    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)

    assert decision.merged is True
    assert decision.reason == "merged"
    assert merge_route.called
    body = merge_route.calls.last.request.read().decode()
    assert "squash" in body
    assert "test-run" in body  # run_id propagated into commit message


# ----------------------------------------------------------------------
# Head ref guard
# ----------------------------------------------------------------------


@respx.mock
async def test_head_ref_not_agent_rejected(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(
            200, json=_pr_payload(head_ref="random-human-branch")
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "head_ref_not_agent"


# ----------------------------------------------------------------------
# [needs-review] marker
# ----------------------------------------------------------------------


@respx.mock
async def test_needs_review_marker_in_title_rejected(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(
            200,
            json=_pr_payload(title="[needs-review] agent saw conflicting sources"),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "needs_review"


@respx.mock
async def test_needs_review_marker_in_body_rejected_case_insensitive(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(
            200,
            json=_pr_payload(body="agent stopped early\n[NEEDS-REVIEW] flaky test"),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "needs_review"


# ----------------------------------------------------------------------
# Size caps
# ----------------------------------------------------------------------


@respx.mock
async def test_too_many_files_rejected(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(
            200,
            json=_pr_payload(changed_files=settings.auto_merge_max_files + 1),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "too_many_files"


@respx.mock
async def test_too_many_lines_rejected(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(
            200,
            json=_pr_payload(
                additions=settings.auto_merge_max_lines, deletions=1
            ),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "too_many_lines"


# ----------------------------------------------------------------------
# Privacy-critical paths
# ----------------------------------------------------------------------


@respx.mock
async def test_privacy_critical_pipeline_path_rejected(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(200, json=_pr_payload())
    )
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7/files").mock(
        return_value=httpx.Response(
            200,
            json=_files_payload(
                [
                    "services/meta-mcp/src/versawiki_meta_mcp/checkers/pipeline.py",
                    "README.md",
                ]
            ),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "privacy_critical_path"
    assert "pipeline.py" in decision.summary


@respx.mock
async def test_privacy_critical_docs_architecture_rejected(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(200, json=_pr_payload())
    )
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7/files").mock(
        return_value=httpx.Response(
            200,
            json=_files_payload(["docs/architecture/overview.md"]),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "privacy_critical_path"


@respx.mock
async def test_agents_md_rejected(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(200, json=_pr_payload())
    )
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7/files").mock(
        return_value=httpx.Response(200, json=_files_payload(["AGENTS.md"]))
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "privacy_critical_path"


# ----------------------------------------------------------------------
# Checks: pending vs. failed
# ----------------------------------------------------------------------


@respx.mock
async def test_pending_checks_returns_wait(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(200, json=_pr_payload())
    )
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7/files").mock(
        return_value=httpx.Response(200, json=_files_payload(["README.md"]))
    )
    respx.get(
        f"{_API}/repos/versawiki/dev/commits/"
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef/check-runs"
    ).mock(
        return_value=httpx.Response(
            200,
            json=_checks_payload(
                runs=[
                    {
                        "name": "test (api)",
                        "status": "in_progress",
                        "conclusion": None,
                    },
                    {
                        "name": "test (orchestrator)",
                        "status": "completed",
                        "conclusion": "success",
                    },
                ]
            ),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "wait"


@respx.mock
async def test_failed_check_blocks(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7").mock(
        return_value=httpx.Response(200, json=_pr_payload())
    )
    respx.get(f"{_API}/repos/versawiki/dev/pulls/7/files").mock(
        return_value=httpx.Response(200, json=_files_payload(["README.md"]))
    )
    respx.get(
        f"{_API}/repos/versawiki/dev/commits/"
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef/check-runs"
    ).mock(
        return_value=httpx.Response(
            200,
            json=_checks_payload(
                runs=[
                    {
                        "name": "test (api)",
                        "status": "completed",
                        "conclusion": "failure",
                    },
                ]
            ),
        )
    )
    merger = _build_merger(settings, tmp_audit)
    decision = await merger.evaluate_and_merge(7)
    assert not decision.merged
    assert decision.reason == "block_failed_checks"
    assert "test (api)" in decision.summary


# ----------------------------------------------------------------------
# list_open_agent_prs filtering
# ----------------------------------------------------------------------


@respx.mock
async def test_list_open_filters_to_agent_branches(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    respx.get(f"{_API}/repos/versawiki/dev/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"number": 1, "head": {"ref": "vw-agent/M1-OK-01"}},
                {"number": 2, "head": {"ref": "josh/manual-fix"}},
                {"number": 3, "head": {"ref": "vw-agent/M1-OK-02"}},
            ],
        )
    )
    merger = _build_merger(settings, tmp_audit)
    nums = await merger.list_open_agent_prs()
    assert nums == [1, 3]

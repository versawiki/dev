"""Claude Agent SDK loop, wired into the orchestrator.

One `AgentRunner.handle(event)` call corresponds to one Claude Agent SDK
run. The agent gets the full Claude Code toolset (Read/Write/Edit/Bash/
Grep) scoped to a working directory containing a fresh clone of the
versawiki repo. It is told via system prompt that it must NOT push to
main and must open a PR through the GitHub CLI / API instead.

We don't import the SDK at module-import time because tests run without
it installed. `_build_options` and the run loop are wrapped in lazy
imports.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import structlog

from ..audit import AuditLog
from ..config import Settings
from ..events import OrchestratorEvent
from ..spending import SpendDecision, SpendingTracker


_log = structlog.get_logger("versawiki_orchestrator.agent")


# Used in _do_run to recover the PR URL from the agent's free-form summary
# in the (common) case the agent opens the PR itself with `curl` rather
# than going through the orchestrator's pr_callback.
_PR_URL_RE = re.compile(r"https://github\.com/[^\s)\]]+/pull/\d+")

# Heuristic: "ticket id" looks like M3-OPS-04 or M2-SUP-07a-fix. We use
# the first match in the agent's prompt to short-circuit duplicate runs.
_TICKET_ID_RE = re.compile(r"M\d+-[A-Z]+-\d+[a-z]?(?:-fix)?")


# The orchestrator's system prompt. Distilled from the cron's overnight
# task file in `local_a87d2ad8-95fe-49b0-981e-31eb9ae20109\uploads\SKILL.md`
# down to the parts that apply 24/7 rather than only at night.
ORCHESTRATOR_SYSTEM_PROMPT = """\
You are the VersaWiki Orchestrator. You operate continuously on a server.

Your job: pick the topmost actionable ticket from the safe list in BACKLOG.md,
implement it cleanly, run the affected service's tests, push your work to a
new branch named `vw-agent/<ticket-id>`, and open a pull request against
`main`. You never push to `main` directly.

Hard rules:
1. ONE ticket per run. Do not chain tickets. If you finish quickly, stop —
   the next tick will start a new run.
2. You may use Bash, Read, Write, Edit, Grep, and Glob. The current working
   directory is a fresh clone of `versawiki/dev`. You may write anywhere
   inside it.
3. NEVER push to `main` (origin/main is branch-protected). NEVER force-push.
   NEVER commit credentials. The repo's `.gitignore` is authoritative for
   what's safe to commit; check `git check-ignore -v` if you're unsure.
4. Do NOT modify `STATUS.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, or
   anything under `docs/architecture/` as part of the ticket's code change.
   Those are updated separately by a human-reviewed PR.
5. Do NOT add new dependencies to a `pyproject.toml` without leaving a
   clear note in the PR body explaining why.
6. Do NOT touch `services/meta-mcp/src/versawiki_meta_mcp/checkers/pipeline.py`
   or `audit/tenant_audit_log.py` — these are privacy-critical and need
   interactive review by Josh.
7. If anything looks weird (test failures you can't explain, conflicts
   between sources, a ticket that's already been done by someone else),
   STOP. Open a draft PR titled `[needs-review]` summarising what you saw
   and exit cleanly.

When you finish, post a short summary (~100 words) of: which ticket you
picked, files changed, test result, and PR URL. The orchestrator process
captures this and records it to the audit log.
"""


@dataclass
class RunResult:
    """Whatever the runner can report about a finished agent run."""

    run_id: str
    event_id: str
    started_at_ns: int
    finished_at_ns: int = 0
    success: bool = False
    summary: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    pr_url: str | None = None
    branch: str | None = None
    error: str | None = None
    # Free-form provenance: tool calls observed, raw messages, etc. Bounded
    # so we don't drag huge transcripts into the audit log.
    extras: dict[str, Any] = field(default_factory=dict)


# Callback signature for "actually open a PR with this branch / commit".
# We pass it in rather than importing the GitHub module to keep this file
# independently testable (and so observe-mode can just inject a no-op).
PrCallback = Callable[[str, str], Awaitable[str | None]]
# (branch_name, summary) -> pr_url


class AgentRunner:
    """Wraps the Claude Agent SDK. Stateless across runs."""

    def __init__(
        self,
        *,
        settings: Settings,
        audit: AuditLog,
        spending: SpendingTracker,
        pr_callback: PrCallback | None = None,
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._spending = spending
        # If `pr_callback` is None we run in pure observation mode — the
        # agent's branch lives only in the local clone and we record what
        # *would* have been pushed.
        self._pr_callback = pr_callback

    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------

    def _check_spend(self) -> SpendDecision:
        return self._spending.evaluate()

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    async def handle(self, event: OrchestratorEvent) -> RunResult:
        """Run one agent loop for `event`. Always returns; never raises."""
        run_id = uuid.uuid4().hex[:12]
        started_ns = time.time_ns()
        result = RunResult(
            run_id=run_id,
            event_id=event.event_id,
            started_at_ns=started_ns,
            model_used=self._settings.model,
        )

        # Spend cap pre-flight.
        decision = self._check_spend()
        self._audit.append(
            "run_preflight",
            {
                "run_id": run_id,
                "event_id": event.event_id,
                "spend_allowed": decision.allowed,
                "spend_reason": decision.reason,
                "spend_summary": decision.summary,
            },
        )
        if not decision.allowed:
            result.success = False
            result.error = f"spend_cap:{decision.reason}"
            result.summary = decision.summary
            result.finished_at_ns = time.time_ns()
            return result

        self._audit.append(
            "run_started",
            {
                "run_id": run_id,
                "event_id": event.event_id,
                "model": self._settings.model,
                "mode": self._settings.mode,
                "kind": event.kind,
            },
        )

        try:
            await self._do_run(event, result)
        except Exception as exc:  # noqa: BLE001 — top-level isolation
            _log.exception("agent_run_failed", run_id=run_id, error=str(exc))
            result.success = False
            result.error = repr(exc)
            result.summary = f"Agent run failed: {exc}"

        result.finished_at_ns = time.time_ns()

        # Record spend. Prefer the SDK-reported dollar figure when we
        # have one (much more accurate than estimating from tokens since
        # it factors in cache hits, tool tokens, etc.). Fall back to the
        # token-based estimate when the SDK didn't tell us.
        sdk_cost = float(result.extras.get("cost_usd_from_sdk") or 0.0)
        if sdk_cost > 0:
            spend_usd = sdk_cost
        else:
            spend_usd = self._spending.estimate_usd(
                result.model_used or self._settings.model,
                result.input_tokens,
                result.output_tokens,
            )
        self._spending.record(
            amount_usd=spend_usd,
            model=result.model_used or self._settings.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            run_id=run_id,
            event_id=event.event_id,
        )

        self._audit.append(
            "run_finished",
            {
                "run_id": run_id,
                "event_id": event.event_id,
                "success": result.success,
                "summary": result.summary,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "spend_usd_estimate": round(spend_usd, 4),
                "pr_url": result.pr_url,
                "branch": result.branch,
                "error": result.error,
            },
        )

        return result

    # ------------------------------------------------------------------
    # SDK glue
    # ------------------------------------------------------------------

    async def _do_run(self, event: OrchestratorEvent, result: RunResult) -> None:
        """The actual SDK call. Lazy-imports so tests can run without the SDK."""
        # Skip-if-branch-exists guard. If the agent has already worked on
        # this ticket in a previous run (branch present in the local repo
        # workdir), don't fire the SDK again — let the previous PR get
        # reviewed / merged first.
        prompt_text = event.to_prompt()
        ticket_match = _TICKET_ID_RE.search(prompt_text)
        if ticket_match is not None:
            ticket_id = ticket_match.group(0)
            existing_branch = self._find_existing_agent_branch(ticket_id)
            if existing_branch is not None:
                self._audit.append(
                    "run_skipped_duplicate_branch",
                    {
                        "run_id": result.run_id,
                        "event_id": event.event_id,
                        "ticket_id": ticket_id,
                        "branch": existing_branch,
                    },
                )
                result.success = False
                result.summary = "branch already exists"
                result.error = "duplicate_branch"
                result.branch = existing_branch
                return

        # The SDK is imported lazily — keeps `pytest` collection cheap and
        # lets us stub it out in unit tests.
        try:
            from claude_agent_sdk import (  # type: ignore
                AssistantMessage,
                ClaudeAgentOptions,
                ClaudeSDKClient,
                ResultMessage,
                TextBlock,
            )
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is not installed; install the orchestrator's "
                "runtime dependencies"
            ) from exc

        options = ClaudeAgentOptions(
            cwd=str(self._settings.repo_workdir),
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            permission_mode="acceptEdits",
            max_turns=self._settings.max_turns_per_run,
            model=self._settings.model,
        )

        summary_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        cost_usd: float = 0.0
        last_branch: str | None = None

        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt_text)
            async for message in client.receive_response():
                # Collect text from assistant turns into the summary.
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            summary_parts.append(block.text)
                # The SDK's ResultMessage carries token totals + final status.
                if isinstance(message, ResultMessage):
                    tokens = _extract_tokens(message)
                    input_tokens = tokens[0]
                    output_tokens = tokens[1]
                    cost_usd = _extract_cost_usd(message)

        # Tail of the summary is the agent's closing paragraph; everything
        # before is intermediate reasoning we don't need to persist.
        summary = "\n\n".join(summary_parts[-3:]) if summary_parts else ""
        result.summary = summary.strip()[:8000]
        result.input_tokens = input_tokens
        result.output_tokens = output_tokens
        if cost_usd > 0:
            # Stash directly so the spending tracker can use the real
            # SDK-reported figure instead of estimating from tokens.
            result.extras["cost_usd_from_sdk"] = round(cost_usd, 6)

        # Look for a PR URL the agent might have included in its summary
        # (the agent often opens PRs itself via curl, bypassing the
        # callback). If we find one, success is True regardless of
        # whether the callback ran.
        url_match = _PR_URL_RE.search(result.summary)
        if url_match is not None:
            result.pr_url = url_match.group(0)
            result.success = True

        # Still try the callback if one is wired in (it's a no-op /
        # logger in observe mode). Don't gate success on it.
        if self._pr_callback is not None:
            try:
                pr_url = await self._pr_callback(last_branch or "", result.summary)
                if pr_url and not result.pr_url:
                    result.pr_url = pr_url
                    result.success = True
            except Exception as exc:  # noqa: BLE001
                if not result.success:
                    result.error = f"pr_callback_failed:{exc!r}"
        elif not result.success:
            # Observation mode + no PR URL extracted: success rides
            # on the agent producing any summary at all.
            result.success = bool(result.summary)

    # ------------------------------------------------------------------
    # Skip-if-branch-exists helper
    # ------------------------------------------------------------------

    def _find_existing_agent_branch(self, ticket_id: str) -> str | None:
        """Return `vw-agent/<ticket_id>...` if such a local branch exists.

        Inspects the configured `repo_workdir` via `git branch --list`.
        Anything we can't introspect (no git dir, command error, etc.)
        returns None so the guard is best-effort and never blocks a
        first-time run.
        """
        repo = self._settings.repo_workdir
        if not repo or not Path(repo).exists():
            return None
        pattern = f"vw-agent/*{ticket_id}*"
        try:
            proc = subprocess.run(
                ["git", "branch", "--list", pattern],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        for line in (proc.stdout or "").splitlines():
            name = line.strip().lstrip("*").strip()
            if name.startswith("vw-agent/") and ticket_id in name:
                return name
        return None

    # ------------------------------------------------------------------
    # Helpers for tests
    # ------------------------------------------------------------------

    @staticmethod
    def system_prompt() -> str:
        return ORCHESTRATOR_SYSTEM_PROMPT


def _extract_tokens(message: Any) -> tuple[int, int]:
    """Pull (input_tokens, output_tokens) out of a ResultMessage.

    The SDK's ResultMessage carries usage as a dict, e.g.
        message.usage = {"input_tokens": ..., "output_tokens": ...}
    Older / forked SDKs may attach them as attributes, or expose a usage
    object instead. Try each shape, falling back to 0.
    """
    # Shape 1: `.usage` dict.
    usage = getattr(message, "usage", None)
    if isinstance(usage, dict):
        return (
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
        )
    # Shape 2: `.usage` object with attributes.
    if usage is not None:
        in_t = getattr(usage, "input_tokens", None)
        out_t = getattr(usage, "output_tokens", None)
        if in_t is not None or out_t is not None:
            return (int(in_t or 0), int(out_t or 0))
    # Shape 3: attributes directly on the message (very old SDKs / mocks).
    in_t = getattr(message, "input_tokens", None)
    out_t = getattr(message, "output_tokens", None)
    if in_t is not None or out_t is not None:
        return (int(in_t or 0), int(out_t or 0))
    return (0, 0)


def _extract_cost_usd(message: Any) -> float:
    """Return the SDK-reported dollar cost, or 0 if not present."""
    cost = getattr(message, "total_cost_usd", None)
    if cost is None:
        return 0.0
    try:
        return float(cost)
    except (TypeError, ValueError):
        return 0.0

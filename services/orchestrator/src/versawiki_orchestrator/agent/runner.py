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

        # Record spend (estimated from token totals reported by the SDK).
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
        last_branch: str | None = None

        async with ClaudeSDKClient(options=options) as client:
            await client.query(event.to_prompt())
            async for message in client.receive_response():
                # Collect text from assistant turns into the summary.
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            summary_parts.append(block.text)
                # The SDK's ResultMessage carries token totals + final status.
                if isinstance(message, ResultMessage):
                    input_tokens = int(getattr(message, "input_tokens", 0) or 0)
                    output_tokens = int(getattr(message, "output_tokens", 0) or 0)

        # Tail of the summary is the agent's closing paragraph; everything
        # before is intermediate reasoning we don't need to persist.
        summary = "\n\n".join(summary_parts[-3:]) if summary_parts else ""
        result.summary = summary.strip()[:8000]
        result.input_tokens = input_tokens
        result.output_tokens = output_tokens

        # If a callback is wired in, ask it to push + open PR. The runner
        # itself doesn't know how to git push — that lives in
        # `versawiki_orchestrator.github`.
        if self._pr_callback is not None:
            # Convention: the agent committed on a branch named after the
            # ticket, in the working clone. The callback walks git to find
            # it. We pass the summary so the PR body uses the agent's own
            # words.
            try:
                pr_url = await self._pr_callback(last_branch or "", result.summary)
                result.pr_url = pr_url
                result.success = pr_url is not None
            except Exception as exc:  # noqa: BLE001
                result.success = False
                result.error = f"pr_callback_failed:{exc!r}"
        else:
            # Observation mode: report success based on the agent's report.
            result.success = bool(result.summary)

    # ------------------------------------------------------------------
    # Helpers for tests
    # ------------------------------------------------------------------

    @staticmethod
    def system_prompt() -> str:
        return ORCHESTRATOR_SYSTEM_PROMPT

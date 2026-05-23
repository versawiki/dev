"""Entrypoint. Wires everything together and runs forever.

Lifecycle:
1. Load settings, open audit log, run startup self-check.
2. In ACT mode: verify branch protection. Refuse to start if main isn't
   protected and PRs aren't required-reviewed.
3. Start the event channel + tick scheduler.
4. Start the control API on a background uvicorn task.
5. Consume events one at a time, dispatch to the agent runner. Honour
   pause flag. Emit `cap_hit_paused` + email if a spend cap trips.
6. SIGINT/SIGTERM → cancel all tasks, flush audit, exit cleanly.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Awaitable, Callable

import structlog
import uvicorn

from .agent import AgentRunner
from .audit import AuditLog
from .config import Settings, load_settings
from .control import ControlState, build_control_app
from .escalation import EmailEscalator, EscalationError
from .events import EventChannel, OrchestratorEvent
from .events.channel import run_tick_scheduler
from .github import BranchProtectionError, GitHubPRWriter
from .spending import SpendingTracker


_log = structlog.get_logger("versawiki_orchestrator")


def _setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


async def _make_pr_callback(
    *,
    settings: Settings,
    audit: AuditLog,
    pr_writer: GitHubPRWriter,
) -> Callable[[str, str], Awaitable[str | None]]:
    """Build the PR callback honoring observe-vs-act mode.

    In `observe` mode, log + audit the intended action, return None. In
    `act` mode, actually push + open the PR.
    """

    async def cb(branch: str, summary: str) -> str | None:
        if settings.mode == "observe" or not branch:
            audit.append(
                "pr_would_open",
                {
                    "branch": branch,
                    "summary_head": summary[:500],
                    "reason": "observe_mode" if settings.mode == "observe" else "no_branch",
                },
            )
            _log.info(
                "observe_mode_pr_skipped",
                branch=branch,
                summary_head=summary[:200],
            )
            return None
        try:
            url = await pr_writer.push_and_open_pr(
                branch=branch,
                title=f"[agent] {branch}",
                body=summary,
            )
            audit.append("pr_opened", {"branch": branch, "url": url})
            return url
        except Exception as exc:  # noqa: BLE001
            audit.append(
                "pr_open_failed",
                {"branch": branch, "error": repr(exc)},
            )
            raise

    return cb


async def _run_one_event(
    *,
    event: OrchestratorEvent,
    runner: AgentRunner,
    audit: AuditLog,
    escalator: EmailEscalator,
    state: ControlState,
) -> None:
    """Dispatch a single event. Wraps everything so a bad event can't kill the loop."""

    async def _body() -> None:
        result = await runner.handle(event)
        state.finish_run(
            {
                "run_id": result.run_id,
                "event_id": result.event_id,
                "success": result.success,
                "summary_head": result.summary[:240],
                "pr_url": result.pr_url,
                "error": result.error,
                "spend_blocked": (result.error or "").startswith("spend_cap:"),
            }
        )
        if result.error and result.error.startswith("spend_cap:"):
            # Try escalating once. If email isn't configured we just log.
            try:
                await escalator.send(
                    subject="[versawiki-orchestrator] spending cap hit — paused",
                    body=(
                        f"The orchestrator paused itself: {result.summary}\n\n"
                        f"Event: {result.event_id}\n"
                        f"Reason: {result.error}\n"
                    ),
                )
            except EscalationError as exc:
                audit.append("escalation_failed", {"reason": str(exc)})
            state.paused = True

    task = asyncio.create_task(_body(), name=f"run-{event.event_id}")
    state.begin_run(
        run_id="(starting)", kind=event.kind, task=task
    )
    try:
        await task
    except asyncio.CancelledError:
        audit.append(
            "run_cancelled",
            {"event_id": event.event_id, "reason": "control_kill"},
        )
        state.finish_run(
            {
                "run_id": "(cancelled)",
                "event_id": event.event_id,
                "success": False,
                "summary_head": "cancelled by control_api",
                "pr_url": None,
                "error": "cancelled",
                "spend_blocked": False,
            }
        )


async def amain(settings: Settings | None = None) -> int:
    """The async entrypoint. Returns an exit code."""
    _setup_logging()
    settings = settings or load_settings()

    audit = AuditLog(settings.audit_db_path)
    audit.append("startup", {"mode": settings.mode})

    spending = SpendingTracker(audit, settings)
    pr_writer = GitHubPRWriter(settings=settings)
    escalator = EmailEscalator(settings)

    # In ACT mode, verify branch protection. In OBSERVE mode, do the check
    # but only warn — we want operators to be able to soak-test before
    # configuring all the GitHub bits.
    try:
        await pr_writer.verify_main_protection()
    except BranchProtectionError as exc:
        if settings.mode == "act":
            _log.error("branch_protection_check_failed", error=str(exc))
            audit.append("startup_aborted", {"reason": str(exc)})
            return 2
        _log.warning(
            "branch_protection_check_warned",
            error=str(exc),
            hint="ACT mode will refuse to start until this is fixed",
        )
        audit.append("branch_protection_warning", {"reason": str(exc)})
    except Exception as exc:  # noqa: BLE001 — network failure shouldn't crash on boot
        if settings.mode == "act":
            _log.error("branch_protection_check_errored_in_act", error=str(exc))
            audit.append("startup_aborted", {"reason": repr(exc)})
            return 2
        _log.warning("branch_protection_check_errored_in_observe", error=str(exc))
        audit.append("branch_protection_warning", {"reason": repr(exc)})

    channel = EventChannel()
    state = ControlState()

    pr_callback = await _make_pr_callback(
        settings=settings, audit=audit, pr_writer=pr_writer
    )
    runner = AgentRunner(
        settings=settings,
        audit=audit,
        spending=spending,
        pr_callback=pr_callback,
    )

    app = build_control_app(
        settings=settings,
        audit=audit,
        spending=spending,
        channel=channel,
        state=state,
    )

    # Background tasks: tick scheduler + uvicorn server.
    tick_task = asyncio.create_task(
        run_tick_scheduler(channel, interval_seconds=settings.tick_interval_seconds),
        name="tick-scheduler",
    )
    uvicorn_config = uvicorn.Config(
        app,
        host=settings.control_api_host,
        port=settings.control_api_port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    server_task = asyncio.create_task(server.serve(), name="control-api")

    # Graceful shutdown wiring.
    stop_event = asyncio.Event()

    def _on_signal(*_: object) -> None:
        _log.info("shutdown_signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with _suppress_signal_error():
            loop.add_signal_handler(sig, _on_signal)

    # Main consume loop.
    async def consume() -> None:
        async for event in channel.iterate():
            if stop_event.is_set():
                break
            if state.paused:
                audit.append(
                    "event_skipped_paused",
                    {"event_id": event.event_id, "kind": event.kind},
                )
                continue
            await _run_one_event(
                event=event,
                runner=runner,
                audit=audit,
                escalator=escalator,
                state=state,
            )

    consume_task = asyncio.create_task(consume(), name="event-consumer")

    # Wait for stop.
    await stop_event.wait()

    # Tear down.
    channel.close()
    tick_task.cancel()
    server.should_exit = True
    consume_task.cancel()
    for t in (tick_task, server_task, consume_task):
        try:
            await asyncio.wait_for(t, timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    audit.append("shutdown", {})
    audit.close()
    return 0


class _suppress_signal_error:
    """Context manager that swallows NotImplementedError on Windows / containers
    where signal handlers can't be installed."""

    def __enter__(self) -> "_suppress_signal_error":
        return self

    def __exit__(self, exc_type: type | None, *_: object) -> bool:
        return exc_type is NotImplementedError


def cli_main() -> None:
    """Synchronous wrapper for the console-script entry point."""
    code = asyncio.run(amain())
    sys.exit(code)


if __name__ == "__main__":
    cli_main()

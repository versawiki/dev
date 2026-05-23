"""FastAPI app for operator control.

Endpoints:
    GET  /control/status            — current run, last 10 runs, spend summary
    POST /control/pause             — agent finishes the current run then idles
    POST /control/resume            — un-pause
    POST /control/kill-current-run  — cancel the in-flight agent task
    POST /control/trigger           — manually enqueue a ManualEvent

All endpoints require `Authorization: Bearer <CONTROL_API_BEARER>`.
`CONTROL_API_BEARER` is generated once and stored in the VM's env file.

We build the app inside a function rather than at module top so the test
suite can construct a fresh app per test without polluting global state.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from ..audit import AuditLog
from ..config import Settings
from ..events import EventChannel, ManualEvent
from ..spending import SpendingTracker


_log = structlog.get_logger("versawiki_orchestrator.control")


@dataclass
class ControlState:
    """Mutable runtime state surfaced via the control API.

    The runner updates `current_run` while a run is in flight; the API
    reads it. `paused` is honoured by the runner before pulling the next
    event from the channel.
    """

    paused: bool = False
    current_run_id: str | None = None
    current_run_started_ns: int | None = None
    current_run_kind: str | None = None
    last_runs: list[dict[str, Any]] = field(default_factory=list)
    # `asyncio.Task` running the current handle() call. Cancelled by
    # /control/kill-current-run.
    current_task: asyncio.Task | None = None

    def begin_run(self, *, run_id: str, kind: str, task: asyncio.Task) -> None:
        self.current_run_id = run_id
        self.current_run_kind = kind
        self.current_run_started_ns = time.time_ns()
        self.current_task = task

    def finish_run(self, summary: dict[str, Any]) -> None:
        self.current_run_id = None
        self.current_run_kind = None
        self.current_run_started_ns = None
        self.current_task = None
        self.last_runs.append(summary)
        # Keep only the last 10.
        if len(self.last_runs) > 10:
            self.last_runs = self.last_runs[-10:]


class TriggerBody(BaseModel):
    """Payload for POST /control/trigger."""

    instruction: str


def build_control_app(
    *,
    settings: Settings,
    audit: AuditLog,
    spending: SpendingTracker,
    channel: EventChannel,
    state: ControlState,
) -> FastAPI:
    """Construct the FastAPI app with closures over the orchestrator's state."""

    app = FastAPI(title="versawiki-orchestrator control API", version="0.1.0")

    bearer_expected = settings.control_api_bearer.get_secret_value()

    def require_bearer(authorization: str | None = Header(default=None)) -> None:
        # If no bearer is configured, refuse all calls — fail closed.
        if not bearer_expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="control api bearer not configured",
            )
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or malformed bearer",
            )
        token = authorization[len("bearer ") :].strip()
        # Constant-time compare to avoid timing leaks. Length differs are
        # fine — they'd already be inferrable from the auth header.
        if not _constant_time_eq(token, bearer_expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="bad bearer",
            )

    auth = Depends(require_bearer)

    @app.get("/control/status", dependencies=[auth])
    def get_status() -> dict[str, Any]:
        decision = spending.evaluate()
        return {
            "mode": settings.mode,
            "paused": state.paused,
            "queue_depth": channel.qsize(),
            "current_run": (
                None
                if state.current_run_id is None
                else {
                    "run_id": state.current_run_id,
                    "kind": state.current_run_kind,
                    "started_at_ns": state.current_run_started_ns,
                    "running_for_seconds": (
                        None
                        if state.current_run_started_ns is None
                        else (time.time_ns() - state.current_run_started_ns) / 1e9
                    ),
                }
            ),
            "last_runs": state.last_runs,
            "spend": {
                "allowed": decision.allowed,
                "reason": decision.reason,
                "summary": decision.summary,
                "today_usd": decision.spent_today_usd,
                "week_usd": decision.spent_this_week_usd,
                "month_usd": decision.spent_this_month_usd,
            },
            "audit_rows": audit.count(),
        }

    @app.post("/control/pause", dependencies=[auth])
    def post_pause() -> dict[str, Any]:
        was = state.paused
        state.paused = True
        audit.append("control_pause", {"was_paused": was, "actor": "control_api"})
        return {"ok": True, "paused": True, "was_paused": was}

    @app.post("/control/resume", dependencies=[auth])
    def post_resume() -> dict[str, Any]:
        was = state.paused
        state.paused = False
        audit.append("control_resume", {"was_paused": was, "actor": "control_api"})
        return {"ok": True, "paused": False, "was_paused": was}

    @app.post("/control/kill-current-run", dependencies=[auth])
    def post_kill() -> dict[str, Any]:
        run_id = state.current_run_id
        task = state.current_task
        if task is None or task.done():
            audit.append("control_kill_noop", {"reason": "no_current_run"})
            return {"ok": True, "killed": False, "reason": "no_current_run"}
        task.cancel()
        audit.append("control_kill", {"run_id": run_id})
        return {"ok": True, "killed": True, "run_id": run_id}

    @app.post("/control/trigger", dependencies=[auth])
    async def post_trigger(body: TriggerBody) -> dict[str, Any]:
        evt = ManualEvent(instruction=body.instruction)
        ok = await channel.put_event(evt)
        audit.append(
            "control_trigger",
            {"event_id": evt.event_id, "queued": ok, "instruction": body.instruction[:200]},
        )
        return {"ok": ok, "event_id": evt.event_id}

    return app


def _constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode("utf-8"), b.encode("utf-8")):
        result |= x ^ y
    return result == 0

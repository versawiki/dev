"""Control API tests using FastAPI's TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from versawiki_orchestrator.audit import AuditLog
from versawiki_orchestrator.config import Settings
from versawiki_orchestrator.control import ControlState, build_control_app
from versawiki_orchestrator.events import EventChannel
from versawiki_orchestrator.spending import SpendingTracker


@pytest.fixture
def app_and_client(tmp_audit: AuditLog, settings: Settings):
    spending = SpendingTracker(tmp_audit, settings)
    channel = EventChannel()
    state = ControlState()
    app = build_control_app(
        settings=settings,
        audit=tmp_audit,
        spending=spending,
        channel=channel,
        state=state,
    )
    client = TestClient(app)
    yield app, client, state, channel
    channel.close()


def test_status_requires_bearer(app_and_client) -> None:
    _, client, _, _ = app_and_client
    r = client.get("/control/status")
    assert r.status_code == 401


def test_status_rejects_wrong_bearer(app_and_client) -> None:
    _, client, _, _ = app_and_client
    r = client.get("/control/status", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_status_ok_with_bearer(app_and_client) -> None:
    _, client, _, _ = app_and_client
    r = client.get(
        "/control/status",
        headers={"Authorization": "Bearer test-bearer-token-do-not-use-in-prod"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "observe"
    assert body["paused"] is False
    assert body["queue_depth"] == 0
    assert body["current_run"] is None
    assert "spend" in body
    assert body["spend"]["allowed"] is True


def test_pause_then_resume(app_and_client) -> None:
    _, client, state, _ = app_and_client
    auth = {"Authorization": "Bearer test-bearer-token-do-not-use-in-prod"}
    r = client.post("/control/pause", headers=auth)
    assert r.status_code == 200 and r.json()["paused"] is True
    assert state.paused is True
    r = client.post("/control/resume", headers=auth)
    assert r.status_code == 200 and r.json()["paused"] is False
    assert state.paused is False


def test_kill_with_no_current_run_is_noop(app_and_client) -> None:
    _, client, _, _ = app_and_client
    r = client.post(
        "/control/kill-current-run",
        headers={"Authorization": "Bearer test-bearer-token-do-not-use-in-prod"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["killed"] is False
    assert body["reason"] == "no_current_run"


def test_trigger_enqueues_manual_event(app_and_client) -> None:
    _, client, _, channel = app_and_client
    r = client.post(
        "/control/trigger",
        headers={"Authorization": "Bearer test-bearer-token-do-not-use-in-prod"},
        json={"instruction": "do the thing"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert channel.qsize() == 1


def test_bearer_not_configured_fails_closed(tmp_audit: AuditLog, settings: Settings) -> None:
    """If the bearer secret isn't set, every endpoint must refuse."""
    bare_settings = settings.model_copy(update={"control_api_bearer": SecretStr("")})
    spending = SpendingTracker(tmp_audit, bare_settings)
    channel = EventChannel()
    state = ControlState()
    app = build_control_app(
        settings=bare_settings,
        audit=tmp_audit,
        spending=spending,
        channel=channel,
        state=state,
    )
    client = TestClient(app)
    r = client.get("/control/status", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503
    channel.close()

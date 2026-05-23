"""Web intake test — FastAPI POST /support/web/messages."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from versawiki_support.agent import SupportAgent
from versawiki_support.intake import web as web_intake
from versawiki_support.llm import StubSupportLLM, SupportLLMResponse


@pytest.fixture(autouse=True)
def _reset_web_threads():  # type: ignore[no-untyped-def]
    web_intake._reset_threads_for_tests()
    yield
    web_intake._reset_threads_for_tests()


def test_post_new_conversation_resolves(agent: SupportAgent, stub_llm: StubSupportLLM) -> None:
    stub_llm.queue(
        SupportLLMResponse(reply_text="API keys: see Settings.", confidence=0.9)
    )
    app = web_intake.build_web_app(agent)
    client = TestClient(app)
    resp = client.post(
        "/support/web/messages",
        json={"text": "How do I get an API key?", "tenant_id": "t1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"].startswith("conv_")
    assert body["status"] == "resolved_by_agent"
    assert body["escalated"] is False
    assert "API keys" in body["reply"]


def test_post_continues_existing_conversation(
    agent: SupportAgent, stub_llm: StubSupportLLM
) -> None:
    stub_llm.queue(SupportLLMResponse(reply_text="ok 1", confidence=0.9))
    stub_llm.queue(SupportLLMResponse(reply_text="ok 2", confidence=0.9))
    app = web_intake.build_web_app(agent)
    client = TestClient(app)
    r1 = client.post(
        "/support/web/messages",
        json={"text": "hi", "tenant_id": "t1"},
    )
    conv_id = r1.json()["conversation_id"]
    r2 = client.post(
        "/support/web/messages",
        json={"text": "second message", "conversation_id": conv_id, "tenant_id": "t1"},
    )
    assert r2.status_code == 200
    assert r2.json()["conversation_id"] == conv_id


def test_post_unknown_conversation_404(agent: SupportAgent) -> None:
    app = web_intake.build_web_app(agent)
    client = TestClient(app)
    resp = client.post(
        "/support/web/messages",
        json={"text": "hi", "conversation_id": "conv_doesnotexist"},
    )
    assert resp.status_code == 404


def test_post_rejects_empty_text(agent: SupportAgent) -> None:
    app = web_intake.build_web_app(agent)
    client = TestClient(app)
    resp = client.post("/support/web/messages", json={"text": ""})
    assert resp.status_code == 422


def test_post_rejects_extra_fields(agent: SupportAgent) -> None:
    app = web_intake.build_web_app(agent)
    client = TestClient(app)
    resp = client.post(
        "/support/web/messages",
        json={"text": "hi", "wat": "huh"},
    )
    assert resp.status_code == 422

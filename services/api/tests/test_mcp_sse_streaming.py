"""SSE streaming response path.

When the client passes ``Accept: text/event-stream`` the response is a
Server-Sent Events stream carrying a single ``message`` event whose
``data`` payload is the JSON-RPC envelope. We assert:

1. The response media type is ``text/event-stream``.
2. The body parses as one SSE event with ``event: message``.
3. The ``data:`` line is the JSON-RPC envelope (same shape as the
   non-SSE path).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from versawiki_api.app import create_app
from versawiki_api.auth.keys import InMemoryApiKeyStore, RedisCachedApiKeyStore
from versawiki_api.config import Settings
from versawiki_api.db.tenant_store import InMemoryTenantStore, TenantRecord
from versawiki_api.deps import set_embedding_provider


class RecordingEmbeddingProvider:
    provider_name = "recording-stub"

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.0] * self.dimension for _ in texts]


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def embedder() -> RecordingEmbeddingProvider:
    return RecordingEmbeddingProvider()


@pytest.fixture
def tenant_store() -> InMemoryTenantStore:
    return InMemoryTenantStore()


@pytest.fixture
def seeded_tenant(tenant_store: InMemoryTenantStore) -> TenantRecord:
    return _run(
        tenant_store.create(
            slug="acme-eng",
            display_name="Acme Engineering",
            plan="free",
        ),
    )


@pytest.fixture
def app_with_tenant(
    settings: Settings,
    api_key_store: RedisCachedApiKeyStore,
    tenant_store: InMemoryTenantStore,
    embedder: RecordingEmbeddingProvider,
    seeded_tenant: TenantRecord,
) -> FastAPI:
    app = create_app(
        settings,
        api_key_store=api_key_store,
        tenant_store=tenant_store,
    )
    set_embedding_provider(app, embedder)
    return app


@pytest.fixture
def tenant_headers(
    api_key_store: RedisCachedApiKeyStore,
    seeded_tenant: TenantRecord,
) -> dict[str, str]:
    _, raw = _run(
        api_key_store.issue(
            tenant_id=seeded_tenant.id,
            label="test-tenant",
            scopes=("query",),
        ),
    )
    return {"Authorization": f"Bearer {raw}"}


@pytest_asyncio.fixture
async def async_client(app_with_tenant: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_tenant)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _parse_sse(raw: str) -> list[dict[str, str]]:
    """Tiny SSE parser. Returns a list of events with ``event`` + ``data``.

    Real SSE supports multi-line ``data:`` fields, ``id:``, ``retry:``,
    comments. For our needs (a single one-line event per response) the
    naive split-on-blank-line approach is enough.
    """
    events: list[dict[str, str]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            field, _, value = line.partition(":")
            event[field.strip()] = value.lstrip()
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_search_sse_response_carries_result_event(
    async_client: AsyncClient,
    tenant_headers: dict[str, str],
    embedder: RecordingEmbeddingProvider,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"q": "stream-me"}},
    }
    headers = {
        **tenant_headers,
        "Accept": "text/event-stream",
    }
    async with async_client.stream("POST", "/mcp", json=body, headers=headers) as response:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        chunks: list[bytes] = []
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)

    raw = b"".join(chunks).decode("utf-8")
    events = _parse_sse(raw)
    assert len(events) >= 1, raw
    event = events[0]
    assert event["event"] == "message"

    envelope = json.loads(event["data"])
    assert envelope["jsonrpc"] == "2.0"
    assert envelope["id"] == 11
    assert "result" in envelope, envelope
    result = envelope["result"]
    assert set(result.keys()) == {"answer_chunks", "pages", "query_id", "took_ms"}

    # Embedding provider was still called once — SSE path doesn't skip work.
    assert embedder.calls == [["stream-me"]]


@pytest.mark.asyncio
async def test_initialize_sse_response_is_valid_event_stream(
    async_client: AsyncClient,
    tenant_headers: dict[str, str],
) -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    headers = {**tenant_headers, "Accept": "text/event-stream"}
    async with async_client.stream("POST", "/mcp", json=body, headers=headers) as response:
        assert response.status_code == 200
        raw = b""
        async for chunk in response.aiter_bytes():
            raw += chunk

    events = _parse_sse(raw.decode("utf-8"))
    assert events
    envelope = json.loads(events[0]["data"])
    assert envelope["result"]["serverInfo"]["name"] == "versawiki-mcp"

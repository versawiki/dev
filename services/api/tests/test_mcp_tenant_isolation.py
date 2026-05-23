"""Cross-tenant isolation on the MCP endpoint.

Tenant identity comes from the API key — *only* from the API key. An
LLM client must not be able to coerce the server into operating on a
different tenant's data by sticking a ``tenant_id`` into the JSON-RPC
``arguments``. We reject such requests with the JSON-RPC
``invalid_params`` error and never consult the smuggled value.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
def tenant_a(tenant_store: InMemoryTenantStore) -> TenantRecord:
    return _run(
        tenant_store.create(
            slug="tenant-a",
            display_name="Tenant A",
            plan="free",
        ),
    )


@pytest.fixture
def tenant_b(tenant_store: InMemoryTenantStore) -> TenantRecord:
    return _run(
        tenant_store.create(
            slug="tenant-b",
            display_name="Tenant B",
            plan="free",
        ),
    )


@pytest.fixture
def app_with_two_tenants(
    settings: Settings,
    api_key_store: RedisCachedApiKeyStore,
    tenant_store: InMemoryTenantStore,
    embedder: RecordingEmbeddingProvider,
    tenant_a: TenantRecord,
    tenant_b: TenantRecord,
) -> FastAPI:
    app = create_app(
        settings,
        api_key_store=api_key_store,
        tenant_store=tenant_store,
    )
    set_embedding_provider(app, embedder)
    return app


@pytest.fixture
def client(app_with_two_tenants: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_with_two_tenants) as test_client:
        yield test_client


@pytest.fixture
def tenant_a_headers(
    api_key_store: RedisCachedApiKeyStore,
    tenant_a: TenantRecord,
) -> dict[str, str]:
    _, raw = _run(
        api_key_store.issue(
            tenant_id=tenant_a.id,
            label="tenant-a-key",
            scopes=("query",),
        ),
    )
    return {"Authorization": f"Bearer {raw}"}


def test_tenant_id_in_arguments_is_rejected(
    client: TestClient,
    tenant_a_headers: dict[str, str],
    tenant_b: TenantRecord,
    embedder: RecordingEmbeddingProvider,
) -> None:
    """A request that smuggles tenant B's id in arguments is refused."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {"q": "x", "tenant_id": tenant_b.id},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_a_headers)
    # HTTP 200 with envelope error — the cross-tenant attempt is a
    # JSON-RPC invalid_params, not a transport failure.
    assert response.status_code == 200
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == -32602
    assert payload["error"]["data"]["offending_field"] == "tenant_id"
    # The embedder must NEVER be reached for a cross-tenant attempt.
    assert embedder.calls == []


def test_read_page_arguments_tenant_id_rejected(
    client: TestClient,
    tenant_a_headers: dict[str, str],
    tenant_b: TenantRecord,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "read_page",
            "arguments": {"page_id": "p1", "tenant_id": tenant_b.id},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_a_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32602


def test_search_uses_key_tenant_only(
    client: TestClient,
    tenant_a_headers: dict[str, str],
    tenant_a: TenantRecord,
    embedder: RecordingEmbeddingProvider,
) -> None:
    """A clean call from tenant A's key runs against tenant A — no path."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"q": "hello"}},
    }
    response = client.post("/mcp", json=body, headers=tenant_a_headers)
    assert response.status_code == 200
    payload = response.json()
    assert "result" in payload
    assert embedder.calls == [["hello"]]

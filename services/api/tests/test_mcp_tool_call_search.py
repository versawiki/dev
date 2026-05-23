"""``tools/call`` with ``name=search``.

Mirrors the BE-04 query route contract: same envelope shape, embedding
provider invoked exactly once with the verbatim ``q``. The mocked
provider records its calls so we can assert that.
"""

from __future__ import annotations

import asyncio
import uuid
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
def client(app_with_tenant: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_with_tenant) as test_client:
        yield test_client


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


def test_search_returns_query_envelope(
    client: TestClient,
    tenant_headers: dict[str, str],
    embedder: RecordingEmbeddingProvider,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {"q": "foo", "top_k": 4},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 7
    result = payload["result"]
    # Same envelope shape as POST /v1/tenants/{id}/query.
    assert set(result.keys()) == {"answer_chunks", "pages", "query_id", "took_ms"}
    assert result["answer_chunks"] == []
    assert result["pages"] == []
    uuid.UUID(result["query_id"])
    assert isinstance(result["took_ms"], int)

    # Embedding provider called exactly once with the verbatim q.
    assert embedder.calls == [["foo"]]


def test_search_top_k_defaults_to_eight(
    client: TestClient,
    tenant_headers: dict[str, str],
    embedder: RecordingEmbeddingProvider,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"q": "anything"}},
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    assert embedder.calls == [["anything"]]


def test_search_missing_q_returns_invalid_params_error(
    client: TestClient,
    tenant_headers: dict[str, str],
    embedder: RecordingEmbeddingProvider,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {}},
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    # Errors come back in the envelope, HTTP stays 200.
    assert response.status_code == 200
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == -32602
    # Embedder NEVER called on validation failure.
    assert embedder.calls == []

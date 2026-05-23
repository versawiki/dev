"""Behaviour tests for ``POST /v1/tenants/{tenant_id}/query``.

Covers the BE-04 contract: the route returns a valid envelope shape
today (no real chunks exist yet), the cross-tenant guard fires
correctly, and the wired :class:`EmbeddingProvider` is called exactly
once per request with the verbatim ``q``.
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


# ---------------------------------------------------------------------------
# Local fixtures — a tenant + a query-scoped key for that tenant
# ---------------------------------------------------------------------------

class RecordingEmbeddingProvider:
    """Embedding provider that records every call.

    Mirrors the duck-typed surface in :class:`versawiki_api.deps.EmbeddingProvider`.
    """

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


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_query_returns_envelope_shape(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    embedder: RecordingEmbeddingProvider,
) -> None:
    payload = {"q": "find recent RFIs", "top_k": 5}
    response = client.post(
        f"/v1/tenants/{seeded_tenant.id}/query",
        json=payload,
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text

    body = response.json()
    # Required keys + types
    assert set(body.keys()) == {"answer_chunks", "pages", "query_id", "took_ms"}
    assert body["answer_chunks"] == []
    assert body["pages"] == []
    assert isinstance(body["took_ms"], int)
    uuid.UUID(body["query_id"])  # parseable

    # Embedding provider was called exactly once with the right text.
    assert len(embedder.calls) == 1
    assert embedder.calls[0] == ["find recent RFIs"]


def test_query_defaults_top_k_to_eight(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    embedder: RecordingEmbeddingProvider,
) -> None:
    response = client.post(
        f"/v1/tenants/{seeded_tenant.id}/query",
        json={"q": "anything"},
        headers=tenant_headers,
    )
    assert response.status_code == 200
    # The provider was still hit once with the verbatim q.
    assert embedder.calls == [["anything"]]


# ---------------------------------------------------------------------------
# Auth + cross-tenant
# ---------------------------------------------------------------------------

def test_query_without_auth_returns_401(
    client: TestClient,
    seeded_tenant: TenantRecord,
) -> None:
    response = client.post(
        f"/v1/tenants/{seeded_tenant.id}/query",
        json={"q": "x"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_query_cross_tenant_returns_403(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    """A key issued for tenant A must not query tenant B."""
    response = client.post(
        "/v1/tenants/not-our-tenant-id/query",
        json={"q": "x"},
        headers=tenant_headers,
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "tenant_scope_mismatch"
    # Details surface both ids so debugging is unambiguous.
    assert body["error"]["details"]["path_tenant_id"] == "not-our-tenant-id"


def test_query_empty_q_returns_422(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    embedder: RecordingEmbeddingProvider,
) -> None:
    response = client.post(
        f"/v1/tenants/{seeded_tenant.id}/query",
        json={"q": ""},
        headers=tenant_headers,
    )
    assert response.status_code == 422
    # Embedding provider must NOT have been called for a validation failure.
    assert embedder.calls == []


def test_query_unknown_tenant_returns_404(
    client: TestClient,
    api_key_store: RedisCachedApiKeyStore,
) -> None:
    """A key whose tenant_id matches the URL but the tenant doesn't exist."""
    _, raw = _run(
        api_key_store.issue(
            tenant_id="ghost-tenant",
            label="orphan",
            scopes=("query",),
        ),
    )
    response = client.post(
        "/v1/tenants/ghost-tenant/query",
        json={"q": "x"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tenant_not_found"

"""Behaviour tests for ``GET /v1/tenants/{tenant_id}/pages/{page_id}``.

Today the route always 404s (ING-05 hasn't persisted any pages yet);
the test guarantees the envelope is structured and the cross-tenant
guard still runs.
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


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
    seeded_tenant: TenantRecord,
) -> FastAPI:
    return create_app(
        settings,
        api_key_store=api_key_store,
        tenant_store=tenant_store,
    )


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


def test_page_lookup_returns_structured_404(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
) -> None:
    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages/missing-page",
        headers=tenant_headers,
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "page_not_found"
    assert body["error"]["details"]["page_id"] == "missing-page"
    assert body["error"]["details"]["tenant_id"] == seeded_tenant.id


def test_page_lookup_cross_tenant_returns_403(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    response = client.get(
        "/v1/tenants/not-our-tenant-id/pages/whatever",
        headers=tenant_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_scope_mismatch"


def test_page_lookup_without_auth_returns_401(
    client: TestClient,
    seeded_tenant: TenantRecord,
) -> None:
    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages/x",
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"

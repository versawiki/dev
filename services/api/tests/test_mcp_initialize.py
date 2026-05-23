"""``initialize`` JSON-RPC method.

The MCP handshake. Returns the server's protocol version + capabilities.
Auth is still required — the API key resolves the tenant for downstream
``tools/call`` invocations, so an unauthenticated initialize is a 401.
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


def test_initialize_returns_server_capabilities(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0.1"},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 1
    assert "result" in payload, payload
    result = payload["result"]
    assert "protocolVersion" in result
    assert isinstance(result["protocolVersion"], str)
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "versawiki-mcp"


def test_initialize_without_auth_returns_401(
    client: TestClient,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }
    response = client.post("/mcp", json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_initialize_preserves_request_id_when_string(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    """JSON-RPC id can be string or int; we must echo it verbatim."""
    body = {
        "jsonrpc": "2.0",
        "id": "abc-123",
        "method": "initialize",
        "params": {},
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    assert response.json()["id"] == "abc-123"

"""``tools/call`` with ``name=read_page`` for an unknown ``page_id``.

The MCP 404 is delivered inside the JSON-RPC envelope, not as an HTTP
404. HTTP status stays 200 — that's the contract the LLM clients
depend on; their transports treat non-200 as transport failure.
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


def test_read_page_unknown_id_returns_envelope_not_found(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "read_page",
            "arguments": {"page_id": "missing-page"},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    # Critically: HTTP is 200; the not-found lives in the JSON-RPC envelope.
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 1
    assert "error" in payload, payload
    err = payload["error"]
    # Application-defined "not_found" code per the JSON-RPC server-error range.
    assert err["code"] == -32004
    assert "Wiki page not found" in err["message"]
    assert err["data"]["page_id"] == "missing-page"
    assert err["data"]["tenant_id"] == seeded_tenant.id


def test_read_chunk_unknown_id_returns_envelope_not_found(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    """Same shape applies to read_chunk's stub."""
    body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "read_chunk",
            "arguments": {"chunk_id": "missing-chunk"},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32004
    assert payload["error"]["data"]["chunk_id"] == "missing-chunk"


def test_unknown_tool_returns_method_not_found(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    """An LLM that hallucinates a tool name gets a clean error."""
    body = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "not-a-real-tool", "arguments": {}},
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32601
    # Surface the canonical list so the client can self-correct.
    assert set(payload["error"]["data"]["available_tools"]) == {
        "search",
        "read_page",
        "read_chunk",
        "list_ontology",
    }


def test_list_ontology_returns_empty_tree(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    """list_ontology with no node_id returns the empty-tree stub."""
    body = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "list_ontology", "arguments": {}},
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"] == {
        "root": {
            "id": "root",
            "label": "",
            "kind": "category",
            "children": [],
        },
    }

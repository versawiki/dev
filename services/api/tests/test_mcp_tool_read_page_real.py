"""``tools/call`` with ``name=read_page`` now backed by the real PageStore.

The MCP envelope shape is unchanged from BE-05; only the body becomes
real when the store has the page. Unknown ids still return the JSON-RPC
``not_found`` envelope inside an HTTP 200. Cross-tenant access is
still refused via the page-not-found path (the tenant is fixed by the
API key; a foreign id resolves to None against the wrong tenant scope).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from versawiki_api.app import create_app
from versawiki_api.auth.keys import InMemoryApiKeyStore, RedisCachedApiKeyStore
from versawiki_api.config import Settings
from versawiki_api.db.tenant_store import InMemoryTenantStore, TenantRecord
from versawiki_api.deps import set_page_store
from versawiki_api.pages_store import InMemoryPageStore, WikiPageRecord


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
def page_store() -> InMemoryPageStore:
    return InMemoryPageStore()


@pytest.fixture
def app_with_tenant(
    settings: Settings,
    api_key_store: RedisCachedApiKeyStore,
    tenant_store: InMemoryTenantStore,
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> FastAPI:
    app = create_app(
        settings,
        api_key_store=api_key_store,
        tenant_store=tenant_store,
    )
    set_page_store(app, page_store)
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


def _make_record(tenant_id: str, *, page_id: str = "pg_known") -> WikiPageRecord:
    return WikiPageRecord(
        id=page_id,
        tenant_id=tenant_id,
        ontology_node_id="topic_a",
        title="A Known Page",
        slug="known-page",
        summary="A brief summary.",
        body_markdown="## Overview\n\nHello.\n",
        chunk_ids=["c1", "c2"],
        related_page_ids=[],
        created_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        is_stale=False,
        version=1,
        source_uri_count=2,
        predominant_doc_types=["rfi"],
    )


def test_read_page_known_id_returns_wikipage_in_result(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> None:
    record = _make_record(seeded_tenant.id)
    _run(page_store.upsert(record))

    body = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "read_page",
            "arguments": {"page_id": record.id},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 11
    assert "result" in payload, payload
    result = payload["result"]
    assert result["page_id"] == record.id
    assert result["slug"] == record.slug
    assert result["title"] == record.title
    assert result["body_md"] == record.body_markdown
    assert result["primary_ontology_node_id"] == record.ontology_node_id
    assert result["last_built_at"] is not None


def test_read_page_unknown_id_still_returns_envelope_not_found(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "read_page",
            "arguments": {"page_id": "no-such-page"},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    payload = response.json()
    assert "error" in payload
    err = payload["error"]
    assert err["code"] == -32004
    assert "Wiki page not found" in err["message"]
    assert err["data"]["page_id"] == "no-such-page"
    assert err["data"]["tenant_id"] == seeded_tenant.id


def test_read_page_cross_tenant_refused_via_not_found(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> None:
    # Put a page under tenant-B; tenant-A's MCP key must not see it.
    foreign = _make_record("other-tenant", page_id="pg_foreign")
    _run(page_store.upsert(foreign))

    body = {
        "jsonrpc": "2.0",
        "id": 33,
        "method": "tools/call",
        "params": {
            "name": "read_page",
            "arguments": {"page_id": "pg_foreign"},
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    payload = response.json()
    # Cross-tenant pages are not surfaced — same not_found envelope.
    assert "error" in payload
    assert payload["error"]["code"] == -32004
    assert payload["error"]["data"]["page_id"] == "pg_foreign"


def test_read_page_rejects_tenant_id_in_arguments(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 44,
        "method": "tools/call",
        "params": {
            "name": "read_page",
            "arguments": {
                "page_id": "pg_known",
                "tenant_id": "other-tenant",
            },
        },
    }
    response = client.post("/mcp", json=body, headers=tenant_headers)
    assert response.status_code == 200
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == -32602
    assert payload["error"]["data"]["offending_field"] == "tenant_id"

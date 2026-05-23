"""Behaviour tests for the new ING-05-backed pages routes.

Replaces the BE-04 always-404 stub. We now have a real
``PageStore`` dependency; tests pre-populate an in-memory store and
assert: known-page -> 200 with the wire shape, missing -> 404,
stale -> 200 + ``Cache-Control: stale=true`` + background rebuild
fires, cross-tenant -> 403, no auth -> 401, by-slug + by-node lookups
both work.
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
from versawiki_api.routers.v1.pages import set_rebuild_hook


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
    # Reset the global rebuild hook between tests; tests that need it
    # install their own and we clean up on exit.
    set_rebuild_hook(None)
    with TestClient(app_with_tenant) as test_client:
        yield test_client
    set_rebuild_hook(None)


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


def _make_record(
    tenant_id: str,
    *,
    page_id: str = "pg_known",
    slug: str = "known-page",
    ontology_node_id: str = "topic_a",
    is_stale: bool = False,
) -> WikiPageRecord:
    return WikiPageRecord(
        id=page_id,
        tenant_id=tenant_id,
        ontology_node_id=ontology_node_id,
        title="A Known Page",
        slug=slug,
        summary="A brief summary.",
        body_markdown="## Overview\n\nHello.\n",
        chunk_ids=["c1", "c2"],
        related_page_ids=[],
        created_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        is_stale=is_stale,
        version=1,
        source_uri_count=2,
        predominant_doc_types=["rfi"],
    )


# ---------------------------------------------------------------------------
# Unknown-page 404
# ---------------------------------------------------------------------------


def test_unknown_page_returns_structured_404(
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


# ---------------------------------------------------------------------------
# Known-page 200
# ---------------------------------------------------------------------------


def test_known_page_returns_wire_envelope(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> None:
    record = _make_record(seeded_tenant.id)
    _run(page_store.upsert(record))

    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages/{record.id}",
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_id"] == record.id
    assert body["slug"] == record.slug
    assert body["title"] == record.title
    assert body["summary"] == record.summary
    assert body["body_md"] == record.body_markdown
    assert body["primary_ontology_node_id"] == record.ontology_node_id
    assert body["chunk_ids"] == record.chunk_ids
    assert body["is_stale"] is False
    assert body["version"] == 1
    assert body["source_uri_count"] == 2
    assert body["predominant_doc_types"] == ["rfi"]


# ---------------------------------------------------------------------------
# Stale page -> cache header + background rebuild
# ---------------------------------------------------------------------------


def test_stale_page_serves_with_cache_header_and_kicks_rebuild(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> None:
    record = _make_record(seeded_tenant.id, is_stale=True)
    _run(page_store.upsert(record))

    seen: list[tuple[str, str]] = []

    async def _hook(tenant_id: str, page_id: str) -> None:
        seen.append((tenant_id, page_id))

    set_rebuild_hook(_hook)

    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages/{record.id}",
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("Cache-Control") == "stale=true"
    body = response.json()
    assert body["is_stale"] is True
    # Background task ran (TestClient runs background tasks to completion).
    assert seen == [(seeded_tenant.id, record.id)]


def test_fresh_page_has_no_stale_cache_header(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> None:
    record = _make_record(seeded_tenant.id, is_stale=False)
    _run(page_store.upsert(record))

    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages/{record.id}",
        headers=tenant_headers,
    )
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") != "stale=true"


# ---------------------------------------------------------------------------
# Cross-tenant + auth guards
# ---------------------------------------------------------------------------


def test_cross_tenant_returns_403_before_existence_check(
    client: TestClient,
    tenant_headers: dict[str, str],
    page_store: InMemoryPageStore,
) -> None:
    # Even with a real page under a different tenant the cross-tenant
    # guard fires first.
    _run(page_store.upsert(_make_record("other-tenant", page_id="pg_other")))
    response = client.get(
        "/v1/tenants/not-our-tenant-id/pages/pg_other",
        headers=tenant_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_scope_mismatch"


def test_no_auth_returns_401(
    client: TestClient,
    seeded_tenant: TenantRecord,
) -> None:
    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages/anything",
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


# ---------------------------------------------------------------------------
# By-slug + by-ontology-node listing
# ---------------------------------------------------------------------------


def test_list_by_slug(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> None:
    record = _make_record(seeded_tenant.id, slug="hello-world")
    _run(page_store.upsert(record))

    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages",
        params={"slug": "hello-world"},
        headers=tenant_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == "hello-world"


def test_list_by_slug_returns_empty_when_unknown(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
) -> None:
    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages",
        params={"slug": "no-such-slug"},
        headers=tenant_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0}


def test_list_by_ontology_node(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
    page_store: InMemoryPageStore,
) -> None:
    r1 = _make_record(
        seeded_tenant.id, page_id="pg1", slug="s1", ontology_node_id="topic_x"
    )
    r2 = _make_record(
        seeded_tenant.id, page_id="pg2", slug="s2", ontology_node_id="topic_x"
    )
    r3 = _make_record(
        seeded_tenant.id, page_id="pg3", slug="s3", ontology_node_id="topic_y"
    )
    for r in (r1, r2, r3):
        _run(page_store.upsert(r))

    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages",
        params={"ontology_node": "topic_x"},
        headers=tenant_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    ids = {item["page_id"] for item in body["items"]}
    assert ids == {"pg1", "pg2"}


def test_list_without_filter_returns_400(
    client: TestClient,
    tenant_headers: dict[str, str],
    seeded_tenant: TenantRecord,
) -> None:
    response = client.get(
        f"/v1/tenants/{seeded_tenant.id}/pages",
        headers=tenant_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_filter"

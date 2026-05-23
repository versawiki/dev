"""Unit tests for :class:`InMemoryTenantStore` and the route wiring.

Real Postgres is not required. These tests exercise:

- ``create`` rejects duplicate slugs.
- ``get`` / ``list`` round-trip correctly.
- The admin route inserts a record and the subsequent ``get_tenant``
  hits it (the BE-01 ticket left this 404; BE-03 fixes it).
- ``list_tenants`` paginates.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from versawiki_api.db.tenant_store import (
    InMemoryTenantStore,
    TenantAlreadyExistsError,
)


# ---------------------------------------------------------------------------
# Store-level
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_in_memory_store_create_and_get() -> None:
    store = InMemoryTenantStore()
    record = await store.create(slug="acme", display_name="Acme Inc")
    assert record.slug == "acme"
    assert record.db_schema_name == "vw_acme"
    assert record.db_role_name == "vw_acme_app"
    # With no provisioner wired, no role_password is generated.
    assert record.role_password is None

    fetched = await store.get(record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.slug == "acme"


@pytest.mark.asyncio
async def test_in_memory_store_duplicate_slug_raises() -> None:
    store = InMemoryTenantStore()
    await store.create(slug="acme", display_name="Acme Inc")
    with pytest.raises(TenantAlreadyExistsError):
        await store.create(slug="acme", display_name="Different display name")


@pytest.mark.asyncio
async def test_in_memory_store_list_paginates() -> None:
    store = InMemoryTenantStore()
    for i in range(5):
        await store.create(slug=f"tenant-{i}", display_name=f"Tenant {i}")
    items, total = await store.list(limit=2, offset=1)
    assert total == 5
    assert len(items) == 2
    # Sorted by created_at ascending — offset=1 skips the first.
    assert items[0].slug == "tenant-1"
    assert items[1].slug == "tenant-2"


@pytest.mark.asyncio
async def test_in_memory_store_get_by_slug() -> None:
    store = InMemoryTenantStore()
    await store.create(slug="acme", display_name="Acme Inc")
    fetched = await store.get_by_slug("acme")
    assert fetched is not None
    assert fetched.slug == "acme"
    assert await store.get_by_slug("never-existed") is None


# ---------------------------------------------------------------------------
# Route-level (uses the existing TestClient + admin_auth_headers fixtures)
# ---------------------------------------------------------------------------

def test_create_then_get_round_trips(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    create = client.post(
        "/v1/admin/tenants",
        json={"slug": "acme", "display_name": "Acme Inc", "plan": "free"},
        headers=admin_auth_headers,
    )
    assert create.status_code == 201, create.text
    tenant_id = create.json()["id"]

    fetched = client.get(f"/v1/admin/tenants/{tenant_id}", headers=admin_auth_headers)
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["id"] == tenant_id
    assert body["slug"] == "acme"
    assert body["db_schema_name"] == "vw_acme"


def test_create_duplicate_slug_returns_409(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    first = client.post(
        "/v1/admin/tenants",
        json={"slug": "acme", "display_name": "Acme Inc", "plan": "free"},
        headers=admin_auth_headers,
    )
    assert first.status_code == 201
    second = client.post(
        "/v1/admin/tenants",
        json={"slug": "acme", "display_name": "Different name", "plan": "free"},
        headers=admin_auth_headers,
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "tenant_already_exists"
    assert body["error"]["details"]["slug"] == "acme"


def test_list_tenants_returns_inserted_rows(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    for i, slug in enumerate(["acme", "globex", "initech"]):
        r = client.post(
            "/v1/admin/tenants",
            json={"slug": slug, "display_name": f"Tenant {i}", "plan": "free"},
            headers=admin_auth_headers,
        )
        assert r.status_code == 201, r.text

    listing = client.get("/v1/admin/tenants", headers=admin_auth_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 3
    assert {row["slug"] for row in body["items"]} == {"acme", "globex", "initech"}

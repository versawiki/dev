"""Unit tests for :class:`InMemoryTenantStore` and the route wiring.

Real Postgres is not required. These tests exercise:

- ``create`` rejects duplicate slugs.
- ``get`` / ``list`` round-trip correctly.
- The admin route inserts a record and the subsequent ``get_tenant``
  hits it (the BE-01 ticket left this 404; BE-03 fixes it).
- ``list_tenants`` paginates.
- The M1-MCP-05 opt-out flag default + ``set_opt_out`` semantics.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from versawiki_api.db.tenant_store import (
    InMemoryTenantStore,
    TenantAlreadyExistsError,
    TenantRecord,
    _strip_password,
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
# M1-MCP-05 — opt-out flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_defaults_opt_out_to_false() -> None:
    store = InMemoryTenantStore()
    record = await store.create(slug="acme", display_name="Acme Inc")
    assert record.opt_out_signature_sharing is False
    # And the read path agrees.
    fetched = await store.get(record.id)
    assert fetched is not None
    assert fetched.opt_out_signature_sharing is False


@pytest.mark.asyncio
async def test_set_opt_out_true_then_get_returns_true() -> None:
    store = InMemoryTenantStore()
    record = await store.create(slug="acme", display_name="Acme Inc")
    updated = await store.set_opt_out(record.id, opt_out_signature_sharing=True)
    assert updated is not None
    assert updated.opt_out_signature_sharing is True
    # And the subsequent get reflects the same value.
    fetched = await store.get(record.id)
    assert fetched is not None
    assert fetched.opt_out_signature_sharing is True
    # The slug index also sees the mutation.
    by_slug = await store.get_by_slug("acme")
    assert by_slug is not None
    assert by_slug.opt_out_signature_sharing is True


@pytest.mark.asyncio
async def test_set_opt_out_round_trip_false() -> None:
    store = InMemoryTenantStore()
    record = await store.create(slug="acme", display_name="Acme Inc")
    await store.set_opt_out(record.id, opt_out_signature_sharing=True)
    back = await store.set_opt_out(record.id, opt_out_signature_sharing=False)
    assert back is not None
    assert back.opt_out_signature_sharing is False


@pytest.mark.asyncio
async def test_set_opt_out_on_missing_id_returns_none() -> None:
    store = InMemoryTenantStore()
    result = await store.set_opt_out("does-not-exist", opt_out_signature_sharing=True)
    assert result is None


def test_strip_password_preserves_opt_out_value() -> None:
    # Build a record with both a password and the opt-out flag set; the
    # stripped copy must lose the password but keep the flag.
    from datetime import datetime, timezone

    raw = TenantRecord(
        id="t-1",
        slug="acme",
        display_name="Acme",
        plan="free",
        db_schema_name="vw_acme",
        db_role_name="vw_acme_app",
        created_at=datetime.now(timezone.utc),
        role_password="hunter2",
        opt_out_signature_sharing=True,
    )
    stripped = _strip_password(raw)
    assert stripped.role_password is None
    assert stripped.opt_out_signature_sharing is True

    # And when role_password is already None the function is a no-op
    # but still carries the opt-out flag through.
    raw2 = TenantRecord(
        id="t-2",
        slug="globex",
        display_name="Globex",
        plan="free",
        db_schema_name="vw_globex",
        db_role_name="vw_globex_app",
        created_at=datetime.now(timezone.utc),
        role_password=None,
        opt_out_signature_sharing=True,
    )
    stripped2 = _strip_password(raw2)
    assert stripped2.opt_out_signature_sharing is True


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

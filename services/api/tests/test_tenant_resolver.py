"""Unit tests for the tenant resolver in :mod:`services_api_tenant`.

Tests the cross-tenant guard and the tenant-store lookup in isolation
from the FastAPI route layer. The dep-yielding ``get_tenant_session``
is exercised by the route tests; here we pin the underlying
:func:`resolve_tenant` contract directly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from versawiki_api.auth.keys import ApiKey
from versawiki_api.db.tenant_store import InMemoryTenantStore, TenantRecord
from versawiki_api.errors import TenantNotFound, TenantScopeMismatch
from versawiki_api.services_api_tenant import resolve_tenant


def _make_key(tenant_id: str) -> ApiKey:
    return ApiKey(
        id="key-id",
        tenant_id=tenant_id,
        prefix="aaaaaaaaaaaa",
        label="test",
        created_at=datetime.now(timezone.utc),
        scopes=("query",),
    )


@pytest.mark.asyncio
async def test_resolve_tenant_returns_record_on_match() -> None:
    store = InMemoryTenantStore()
    rec = await store.create(slug="acme-eng", display_name="Acme", plan="free")
    key = _make_key(rec.id)

    out = await resolve_tenant(
        api_key=key,
        tenant_id=rec.id,
        tenant_store=store,
    )
    assert isinstance(out, TenantRecord)
    assert out.id == rec.id
    assert out.slug == "acme-eng"
    assert out.db_schema_name == "vw_acme-eng"


@pytest.mark.asyncio
async def test_resolve_tenant_rejects_cross_tenant() -> None:
    """Key for tenant A + path for tenant B -> 403 ``tenant_scope_mismatch``.

    The guard runs BEFORE the tenant lookup so an attacker probing for
    existence with a foreign key always gets the same 403.
    """
    store = InMemoryTenantStore()
    rec_a = await store.create(slug="tenant-a", display_name="A", plan="free")
    rec_b = await store.create(slug="tenant-b", display_name="B", plan="free")
    key_for_a = _make_key(rec_a.id)

    with pytest.raises(TenantScopeMismatch) as exc_info:
        await resolve_tenant(
            api_key=key_for_a,
            tenant_id=rec_b.id,
            tenant_store=store,
        )
    assert exc_info.value.code == "tenant_scope_mismatch"
    assert exc_info.value.status_code == 403
    assert exc_info.value.details["api_key_tenant_id"] == rec_a.id
    assert exc_info.value.details["path_tenant_id"] == rec_b.id


@pytest.mark.asyncio
async def test_resolve_tenant_unknown_tenant_returns_404() -> None:
    """Key + URL agree but the tenant doesn't exist -> 404."""
    store = InMemoryTenantStore()
    key = _make_key("ghost-id")

    with pytest.raises(TenantNotFound) as exc_info:
        await resolve_tenant(
            api_key=key,
            tenant_id="ghost-id",
            tenant_store=store,
        )
    assert exc_info.value.code == "tenant_not_found"


@pytest.mark.asyncio
async def test_resolve_tenant_scope_guard_runs_before_existence_check() -> None:
    """Cross-tenant for a non-existent target tenant must still 403, not 404.

    Otherwise an attacker can use the 404-vs-403 distinction to probe
    whether a tenant id exists.
    """
    store = InMemoryTenantStore()
    rec = await store.create(slug="real", display_name="Real", plan="free")
    key = _make_key(rec.id)

    with pytest.raises(TenantScopeMismatch):
        await resolve_tenant(
            api_key=key,
            tenant_id="non-existent-id",
            tenant_store=store,
        )

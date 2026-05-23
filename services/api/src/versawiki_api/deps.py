"""FastAPI dependency-injection wiring.

This module is the single seam where future tickets plug in:

- ``get_db_session`` -> BE-03 replaces with a real async SQLAlchemy
  session bound to the app's engine.
- ``api_key_required`` / ``admin_key_required`` -> BE-02 wired the
  real argon2-validated, in-memory store; BE-03 adds a Postgres-
  backed alternative behind the same protocol.
- ``get_current_tenant`` -> Resolves the tenant from the validated
  API key against the tenant directory store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from .auth.keys import ApiKey
from .auth.middleware import (
    AdminApiKey,
    CurrentApiKey,
    admin_key_required,
    api_key_required,
    get_api_key_store,
    set_api_key_store,
)
from .config import Settings, get_settings
from .db.engine import SessionDep, get_session
from .db.tenant_store import InMemoryTenantStore, TenantStore
from .logging import get_logger

log = get_logger(__name__)


def settings_dep(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


get_db_session = get_session
DbSession = SessionDep


def get_tenant_store(request: Request) -> TenantStore:
    store = getattr(request.app.state, "tenant_store", None)
    if store is None:
        store = InMemoryTenantStore()
        request.app.state.tenant_store = store
    return store


TenantStoreDep = Annotated[TenantStore, Depends(get_tenant_store)]


StubApiKey = ApiKey


@dataclass(frozen=True)
class StubTenantContext:
    """Resolved tenant for the current request."""

    tenant_id: str
    tenant_slug: str
    db_schema_name: str
    is_stub: bool = True


def get_current_tenant(current_api_key: CurrentApiKey) -> StubTenantContext:
    return StubTenantContext(
        tenant_id=current_api_key.tenant_id,
        tenant_slug=current_api_key.tenant_slug,
        db_schema_name=f"vw_{current_api_key.tenant_slug}",
        is_stub=current_api_key.is_stub,
    )


CurrentTenant = Annotated[StubTenantContext, Depends(get_current_tenant)]


__all__ = [
    "ApiKey",
    "StubApiKey",
    "AdminApiKey",
    "CurrentApiKey",
    "CurrentTenant",
    "DbSession",
    "Settings",
    "SettingsDep",
    "StubTenantContext",
    "TenantStoreDep",
    "admin_key_required",
    "api_key_required",
    "get_api_key_store",
    "get_current_tenant",
    "get_db_session",
    "get_tenant_store",
    "set_api_key_store",
    "settings_dep",
]

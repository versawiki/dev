"""FastAPI dependency-injection wiring.

This module is the single seam where future tickets plug in:

- ``get_db_session`` -> BE-03 will replace the stub with a real
  SQLAlchemy session bound to the tenant's schema.
- ``api_key_required`` / ``admin_key_required`` -> BE-02 has wired the
  real argon2-validated, in-memory store (with a Redis-cache wrapper
  whose Redis client lands in BE-02b).
- ``get_current_tenant`` -> BE-03 will resolve the tenant from the
  validated API key's ``tenant_id`` against ``vw_admin.tenants``.

Today, ``api_key_required``/``admin_key_required`` are the real deps
re-exported from :mod:`versawiki_api.auth.middleware`; ``ApiKey`` is
the real domain model from :mod:`versawiki_api.auth.keys`. The
``StubApiKey`` name lives on as an alias for one release so any
in-flight branches keep importing successfully.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

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
from .errors import NotImplementedYet
from .logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings_dep(request: Request) -> Settings:
    """Return the Settings the app was built with.

    Tests pass a custom ``Settings`` into ``create_app``; that instance
    is stored on ``app.state.settings``. Falling back to the cached
    global keeps this dep usable outside a request (e.g. background
    jobs that import the dep module directly).
    """
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


# ---------------------------------------------------------------------------
# DB session (stub; BE-03 wires the real one)
# ---------------------------------------------------------------------------

def get_db_session() -> Any:
    """Yield a SQLAlchemy session.

    Will be implemented by BE-03 alongside the per-tenant schema
    provisioner. Until then, callers that actually need DB access
    receive a 501.
    """
    raise NotImplementedYet(
        message="Database session unavailable; BE-03 has not been merged yet.",
    )


DbSession = Annotated[Any, Depends(get_db_session)]


# ---------------------------------------------------------------------------
# API-key auth (real, via auth.middleware)
# ---------------------------------------------------------------------------

# BE-01 shipped StubApiKey. BE-02 swaps to the real ApiKey but keeps
# the legacy name as an alias for one release so any half-merged branch
# still imports cleanly.
StubApiKey = ApiKey


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StubTenantContext:
    """Resolved tenant for the current request.

    Today this is just whatever the API key advertises. BE-03 swaps
    the body to perform the ``SET search_path`` / ``SET ROLE`` dance
    described in docs/architecture/v1.md section 4.
    """

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
    "admin_key_required",
    "api_key_required",
    "get_api_key_store",
    "get_current_tenant",
    "get_db_session",
    "set_api_key_store",
    "settings_dep",
]

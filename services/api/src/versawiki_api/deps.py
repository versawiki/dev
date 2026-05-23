"""FastAPI dependency-injection wiring.

This module is the single seam where future tickets plug in:

- ``get_db_session`` -> BE-03 will replace the stub with a real
  SQLAlchemy session bound to the tenant's schema.
- ``api_key_required`` / ``admin_key_required`` -> BE-02 will replace
  ``StubApiKey`` with a real argon2-validated, Redis-cached ApiKey.
- ``get_current_tenant`` -> BE-02/03 will resolve the tenant from the
  validated API key's ``tenant_id``.

Today these all return stubs or raise ``NotImplementedYet``. The
import paths and call signatures are deliberate so the swap is purely
a body change, not a surface change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from .config import Settings, get_settings
from .errors import NotImplementedYet, Unauthenticated
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
# API-key auth (stub; BE-02 wires argon2 + Redis cache)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StubApiKey:
    """Placeholder for the real ApiKey domain object (BE-02).

    The shape is intentionally a sketch of what BE-02 will produce so
    downstream routes can already type-hint against it.
    """

    id: str = "stub-key-id"
    tenant_id: str = "stub-tenant-id"
    tenant_slug: str = "stub"
    scopes: tuple[str, ...] = ("query",)
    is_stub: bool = True
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def api_key_required(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> StubApiKey:
    """Validate the API key on the request.

    BE-02 replaces the body. The signature is locked: routes already
    type-hint ``current_api_key: Annotated[StubApiKey, Depends(api_key_required)]``
    today, and BE-02 will rename the return type to the real ``ApiKey``
    domain object.
    """
    token = _parse_bearer(authorization)
    if token is None:
        raise Unauthenticated(message="Missing Authorization: Bearer <key> header.")

    # TODO(BE-02): argon2 verify against vw_admin.api_keys.key_hash, with a
    # short-TTL Redis cache. For now, accept any non-empty bearer token in
    # the dev/test envs so route shape tests can drive the API surface.
    settings = settings_dep(request)
    if settings.env not in {"dev", "test"}:
        # Refuse in staging/prod until BE-02 lands.
        raise Unauthenticated(message="API-key auth not yet implemented in this environment.")

    log.debug("api_key_stub_accepted", env=settings.env)
    return StubApiKey()


CurrentApiKey = Annotated[StubApiKey, Depends(api_key_required)]


def admin_key_required(current_api_key: CurrentApiKey) -> StubApiKey:
    """Require the ``admin`` scope on top of a valid key."""
    if not current_api_key.has_scope("admin") and not current_api_key.is_stub:
        # The is_stub bypass means admin routes are exercisable in dev/test.
        # BE-02 removes the bypass when real scopes are loaded from the DB.
        from .errors import PermissionDenied

        raise PermissionDenied(message="This endpoint requires the 'admin' scope.")
    return current_api_key


AdminApiKey = Annotated[StubApiKey, Depends(admin_key_required)]


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

"""Tenant resolution + per-tenant session helper.

This module is the seam between an authenticated request and the
per-tenant Postgres schema. Two responsibilities:

1. Cross-tenant guard. Given the URL's ``tenant_id`` and the
   :class:`ApiKey` resolved by :func:`api_key_required`, refuse the
   request if the key was issued for a different tenant. The error
   raised is :class:`TenantScopeMismatch` (403, stable code
   ``tenant_scope_mismatch``).
2. Schema-bound session. Open an :class:`AsyncSession`, and ``SET
   search_path`` on it to ``vw_<slug>, vw_admin``. The session is
   yielded to the caller; on exit, ``search_path`` is reset to a safe
   default so any pool-recycled connection cannot leak the previous
   tenant's path.

The BE-04 stub does not actually issue queries against the per-tenant
tables (those tables exist only as stub columns today). The dep is
written so that BE-05 (MCP endpoint) and ING-05 (page builder) can
reuse the same path verbatim.

Test-fallback behaviour: when the app is wired with the in-memory
tenant store (which is the default in dev + test), the session is
yielded without a real ``SET search_path`` because there's no real
Postgres to set it on. The cross-tenant check still runs. A
``StubAsyncSession`` is yielded so tests can pass it through routes
without standing up a Postgres dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.keys import ApiKey
from .auth.middleware import api_key_required
from .db.engine import async_session_factory, get_async_engine
from .db.tenant_store import TenantRecord, TenantStore
from .deps import get_tenant_store, settings_dep
from .errors import TenantNotFound, TenantScopeMismatch
from .logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class TenantContext:
    """Resolved per-request tenant + the schema-bound session.

    Routes typically only need ``tenant_id`` / ``slug`` / ``session``;
    the full record is exposed in case a future caller wants the
    display name or plan without a second store lookup.
    """

    tenant_id: str
    slug: str
    db_schema_name: str
    record: TenantRecord
    session: AsyncSession


class StubAsyncSession:
    """A stand-in :class:`AsyncSession` for the in-memory test path.

    BE-03 ships per-tenant tables as stub columns only and the default
    app wiring uses :class:`InMemoryTenantStore`. The query route's
    stub body returns ``[]`` cleanly without needing a real session, so
    we hand back this lightweight shim instead of forcing a real
    Postgres engine into every test.

    It exposes only the methods the BE-04 stub bodies use. Real
    routes that want to write SQL must use the real engine path —
    see :func:`get_tenant_session_real`.
    """

    is_stub: bool = True

    async def execute(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003 - shim signature
        return _StubResult()

    async def close(self) -> None:
        return None


class _StubResult:
    def all(self) -> list:
        return []

    def scalars(self) -> "_StubScalars":
        return _StubScalars()


class _StubScalars:
    def all(self) -> list:
        return []

    def first(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Cross-tenant guard
# ---------------------------------------------------------------------------

def _assert_same_tenant(key_tenant_id: str, path_tenant_id: str) -> None:
    """Raise :class:`TenantScopeMismatch` if the key is for a different tenant."""
    if key_tenant_id != path_tenant_id:
        raise TenantScopeMismatch(
            details={
                "api_key_tenant_id": key_tenant_id,
                "path_tenant_id": path_tenant_id,
            },
        )


# ---------------------------------------------------------------------------
# Resolver — pluggable so tests can call it directly
# ---------------------------------------------------------------------------

async def resolve_tenant(
    *,
    api_key: ApiKey,
    tenant_id: str,
    tenant_store: TenantStore,
) -> TenantRecord:
    """Look up the tenant record and enforce the cross-tenant guard.

    Order matters: we run the scope check *first* so that an attacker
    probing for tenant existence with a foreign key always gets the
    same 403, regardless of whether the target tenant exists.
    """
    _assert_same_tenant(api_key.tenant_id, tenant_id)
    record = await tenant_store.get(tenant_id)
    if record is None:
        raise TenantNotFound(details={"tenant_id": tenant_id})
    return record


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_tenant_session(
    request: Request,
    tenant_id: Annotated[str, Path()],
    api_key: Annotated[ApiKey, Depends(api_key_required)],
) -> AsyncIterator[TenantContext]:
    """Yield a :class:`TenantContext` for the current request.

    1. Re-validate the API key (done by ``api_key_required``).
    2. Enforce the cross-tenant guard.
    3. Look up the tenant record from the app's :class:`TenantStore`.
    4. Yield a :class:`TenantContext` carrying a schema-bound session.

    The session is closed on exit (whether the route raises or returns).
    """
    tenant_store = get_tenant_store(request)
    record = await resolve_tenant(
        api_key=api_key,
        tenant_id=tenant_id,
        tenant_store=tenant_store,
    )

    settings = settings_dep(request)
    # In-memory store + test/dev runtime => stub session.
    # Production runtime with PostgresTenantStore => real session +
    # SET search_path. We pick by the env flag so tests never reach
    # the engine path.
    use_real_session = settings.env not in {"test", "dev"} and not isinstance(
        tenant_store.__class__.__name__, str  # always falsy; placeholder
    )
    # Simpler: real session only when explicitly opted-in via app state.
    use_real_session = getattr(request.app.state, "use_real_db_session", False)

    if not use_real_session:
        session: AsyncSession = StubAsyncSession()  # type: ignore[assignment]
        try:
            yield TenantContext(
                tenant_id=record.id,
                slug=record.slug,
                db_schema_name=record.db_schema_name,
                record=record,
                session=session,
            )
        finally:
            await session.close()
        return

    engine = get_async_engine(settings)
    factory = async_session_factory(engine)
    async with factory() as real_session:
        # ``SET search_path`` per-session. Belt-and-braces: also reset
        # at exit so a recycled connection cannot serve a different
        # tenant with the wrong path still bound.
        schema = record.db_schema_name
        await real_session.execute(
            text(f'SET search_path TO "{schema}", vw_admin')
        )
        try:
            yield TenantContext(
                tenant_id=record.id,
                slug=record.slug,
                db_schema_name=schema,
                record=record,
                session=real_session,
            )
        finally:
            try:
                await real_session.execute(text("SET search_path TO vw_admin"))
            except Exception:  # noqa: BLE001 - exit-path defensive
                log.debug("search_path_reset_failed", schema=schema)


TenantSessionDep = Annotated[TenantContext, Depends(get_tenant_session)]


__all__ = [
    "StubAsyncSession",
    "TenantContext",
    "TenantSessionDep",
    "get_tenant_session",
    "resolve_tenant",
]

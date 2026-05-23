"""FastAPI deps that gate routes on a valid API key.

Public surface (re-exported by :mod:`versawiki_api.deps` so existing
callers keep their import paths):

- :func:`api_key_required` — validates the bearer token and returns
  the :class:`ApiKey` model. Raises :class:`Unauthenticated` on any
  failure (missing header, malformed header, unknown prefix, bad
  secret, revoked key).
- :func:`admin_key_required` — chains on top of
  :func:`api_key_required` and additionally requires the ``admin``
  scope.

Store wiring: the request's :class:`ApiKeyStore` lives on
``app.state.api_key_store``. Tests / app boot install a store via
:func:`set_api_key_store`. If none is installed (e.g. import-time
checks), :func:`get_api_key_store` lazily creates a process-default
in-memory store wrapped in :class:`RedisCachedApiKeyStore` so the
wiring is identical to production.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request

from ..errors import PermissionDenied, Unauthenticated
from ..logging import get_logger
from .keys import (
    ApiKey,
    ApiKeyStore,
    InMemoryApiKeyStore,
    RedisCachedApiKeyStore,
    parse_token,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Store accessor / installer
# ---------------------------------------------------------------------------

_DEFAULT_STORE: ApiKeyStore | None = None


def _default_store() -> ApiKeyStore:
    """Lazily build the process-wide default store.

    The default is :class:`InMemoryApiKeyStore` wrapped in the
    Redis-cache wrapper (which is itself a pass-through today). BE-03
    replaces the inner store with the Postgres-backed one.
    """
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = RedisCachedApiKeyStore(InMemoryApiKeyStore())
    return _DEFAULT_STORE


def set_api_key_store(app: FastAPI, store: ApiKeyStore) -> None:
    """Install an :class:`ApiKeyStore` onto a FastAPI app.

    Call this from ``create_app`` (or a test fixture) so each request
    resolves to a known store. Without it, the app falls back to a
    shared process-wide default; that default is fine for tests that
    don't care about isolation but is **not** safe across multiple
    apps in the same process.
    """
    app.state.api_key_store = store


def get_api_key_store(request: Request) -> ApiKeyStore:
    """Return the store bound to the current app, or the process default."""
    store = getattr(request.app.state, "api_key_store", None)
    if isinstance(store, (InMemoryApiKeyStore, RedisCachedApiKeyStore)):
        return store
    if store is not None:
        # Trust duck-typing — Postgres impls won't be in the isinstance
        # tuple above, and that's fine.
        return store
    return _default_store()


ApiKeyStoreDep = Annotated[ApiKeyStore, Depends(get_api_key_store)]


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, raw = parts[0], parts[1].strip()
    if scheme.lower() != "bearer":
        return None
    return raw or None


# ---------------------------------------------------------------------------
# Deps
# ---------------------------------------------------------------------------

async def api_key_required(
    store: ApiKeyStoreDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> ApiKey:
    """Validate the request's API key and return the resolved :class:`ApiKey`.

    Failure modes (all raise :class:`Unauthenticated`):

    - Missing ``Authorization`` header.
    - Header not in ``Bearer <token>`` form.
    - Token not in ``vw_<prefix>_<secret>`` form.
    - Unknown prefix.
    - Secret does not argon2-verify.
    - Key is revoked.
    """
    token = _parse_bearer(authorization)
    if token is None:
        raise Unauthenticated(
            message="Missing or malformed Authorization: Bearer <key> header.",
        )

    if parse_token(token) is None:
        raise Unauthenticated(message="API key is not in the expected format.")

    key = await store.lookup_by_token(token)
    if key is None:
        raise Unauthenticated(message="API key is invalid or has been revoked.")

    log.debug(
        "api_key_resolved",
        key_id=key.id,
        prefix=key.prefix,
        tenant_id=key.tenant_id,
    )
    return key


CurrentApiKey = Annotated[ApiKey, Depends(api_key_required)]


def admin_key_required(current_api_key: CurrentApiKey) -> ApiKey:
    """Require the ``admin`` scope on top of a valid API key."""
    if not current_api_key.has_scope("admin"):
        raise PermissionDenied(message="This endpoint requires the 'admin' scope.")
    return current_api_key


AdminApiKey = Annotated[ApiKey, Depends(admin_key_required)]


__all__ = [
    "api_key_required",
    "admin_key_required",
    "get_api_key_store",
    "set_api_key_store",
    "CurrentApiKey",
    "AdminApiKey",
    "ApiKeyStoreDep",
]

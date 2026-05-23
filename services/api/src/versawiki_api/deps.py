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
from .pages_store import InMemoryPageStore, PageStore

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




# ---------------------------------------------------------------------------
# Embedding provider (BE-04)
# ---------------------------------------------------------------------------

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Duck-typed interface that matches `versawiki_ingestion.embedding.EmbeddingProvider`.

    The api package does not depend on ``versawiki_ingestion`` at
    runtime (they're sibling services), so we re-declare the minimum
    surface here. Any provider with ``embed(list[str]) -> list[list[float]]``
    plus ``dimension`` + ``provider_name`` attributes satisfies it,
    which includes the ingestion service's ``StubEmbeddingProvider``
    and ``OpenAIEmbeddingProvider``.
    """

    dimension: int
    provider_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class _LocalStubEmbeddingProvider:
    """Process-local fallback when no provider is wired.

    Deterministic but stripped down — the production tests reach for
    the ingestion service's ``StubEmbeddingProvider`` (canonical) when
    the test harness has added ingestion to ``sys.path``. This local
    stub exists so the api process boots cleanly in dev when ingestion
    isn't on the path.
    """

    provider_name = "local-stub"

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.0] * self.dimension for _ in texts]


_DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider | None = None


def set_embedding_provider(app, provider: EmbeddingProvider) -> None:
    """Install an embedding provider onto a FastAPI app's state."""
    app.state.embedding_provider = provider


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    """Return the request's wired embedding provider, defaulting to a stub.

    Production wiring sets the OpenAI provider on ``app.state`` at
    startup; tests can either inject the canonical ingestion stub via
    :func:`set_embedding_provider` or rely on the lazy
    ``_LocalStubEmbeddingProvider`` fallback.
    """
    provider = getattr(request.app.state, "embedding_provider", None)
    if provider is not None:
        return provider
    global _DEFAULT_EMBEDDING_PROVIDER
    if _DEFAULT_EMBEDDING_PROVIDER is None:
        _DEFAULT_EMBEDDING_PROVIDER = _LocalStubEmbeddingProvider()
    request.app.state.embedding_provider = _DEFAULT_EMBEDDING_PROVIDER
    return _DEFAULT_EMBEDDING_PROVIDER


EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


# ---------------------------------------------------------------------------
# Page store (ING-05)
# ---------------------------------------------------------------------------


def set_page_store(app, store: PageStore) -> None:
    """Install a :class:`PageStore` onto a FastAPI app's state."""
    app.state.page_store = store


def get_page_store(request: Request) -> PageStore:
    """Return the request's wired :class:`PageStore`.

    Defaults to a process-local :class:`InMemoryPageStore` when the
    app didn't install one. Production replaces this with the
    Postgres-backed impl via :func:`set_page_store` in ``create_app``.
    """
    store = getattr(request.app.state, "page_store", None)
    if store is not None:
        return store
    store = InMemoryPageStore()
    request.app.state.page_store = store
    return store


PageStoreDep = Annotated[PageStore, Depends(get_page_store)]


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
    "get_page_store",
    "get_tenant_store",
    "set_api_key_store",
    "set_page_store",
    "settings_dep",
    "EmbeddingProvider",
    "EmbeddingProviderDep",
    "PageStore",
    "PageStoreDep",
    "get_embedding_provider",
    "set_embedding_provider",
]

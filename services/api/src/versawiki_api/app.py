"""FastAPI app factory.

``create_app`` is invoked by uvicorn (with ``--factory``) and by tests
(directly). Anything that must run on every request lives on the
returned ``FastAPI`` instance: routers, middleware, error handlers,
OpenAPI tweaks.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __service_name__, __version__
from .auth.keys import ApiKeyStore, InMemoryApiKeyStore, RedisCachedApiKeyStore
from .auth.middleware import set_api_key_store
from .config import Settings, get_settings
from .db.tenant_store import InMemoryTenantStore, TenantStore
from .errors import install_error_handlers
from .logging import configure_logging, get_logger
from .routers import register_routers


def set_tenant_store(app: FastAPI, store: TenantStore) -> None:
    """Install a :class:`TenantStore` onto a FastAPI app."""
    app.state.tenant_store = store


def create_app(
    settings: Settings | None = None,
    *,
    api_key_store: ApiKeyStore | None = None,
    tenant_store: TenantStore | None = None,
) -> FastAPI:
    """Build a fully wired FastAPI app.

    Args:
        settings: Override for tests. In normal runtime the cached
            ``get_settings()`` instance is used.
        api_key_store: Override for tests. Defaults to an in-memory
            store wrapped in the Redis-cache wrapper.
        tenant_store: Override for tests. Defaults to
            :class:`InMemoryTenantStore` with no provisioner — see
            :mod:`versawiki_api.db.tenant_store`. Real deployments
            inject :class:`PostgresTenantStore` with a real
            :class:`TenantProvisioner` from a startup hook.
    """
    settings = settings or get_settings()
    configure_logging(settings)
    log = get_logger(__name__)

    app = FastAPI(
        title="Versawiki API",
        version=__version__,
        description=(
            "Query API + admin surface for Versawiki. The per-tenant "
            "MCP-over-HTTP endpoint will mount here too (see BE-05)."
        ),
        openapi_url="/openapi.json",
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url="/redoc" if settings.env != "prod" else None,
    )

    app.state.settings = settings
    app.state.service_name = __service_name__
    app.state.service_version = __version__

    if api_key_store is None:
        api_key_store = RedisCachedApiKeyStore(InMemoryApiKeyStore())
    set_api_key_store(app, api_key_store)

    if tenant_store is None:
        tenant_store = InMemoryTenantStore()
    set_tenant_store(app, tenant_store)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_error_handlers(app)
    register_routers(app)

    log.info(
        "app_created",
        service=__service_name__,
        version=__version__,
        env=settings.env,
        cors_origins=settings.cors_origins,
    )
    return app

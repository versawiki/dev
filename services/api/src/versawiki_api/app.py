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
from .config import Settings, get_settings
from .errors import install_error_handlers
from .logging import configure_logging, get_logger
from .routers import register_routers


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully wired FastAPI app.

    Args:
        settings: Override for tests. In normal runtime the cached
            ``get_settings()`` instance is used.
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
        # Versioned routes live under /v1/...; OpenAPI advertises them at /openapi.json.
        openapi_url="/openapi.json",
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url="/redoc" if settings.env != "prod" else None,
    )

    app.state.settings = settings
    app.state.service_name = __service_name__
    app.state.service_version = __version__

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

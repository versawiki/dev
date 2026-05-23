"""Router registration.

Add a new top-level router by importing it here and appending it to
``register_routers``. Keep nested router trees (e.g. ``admin/``) in
their own subpackages.
"""

from __future__ import annotations

from fastapi import FastAPI

from ..mcp.router import router as mcp_router
from .admin import admin_router
from .health import router as health_router
from .v1 import v1_router


def register_routers(app: FastAPI) -> None:
    """Mount every router onto the app.

    Order is cosmetic only (it affects OpenAPI tag grouping).
    """
    app.include_router(health_router)
    app.include_router(admin_router, prefix="/v1/admin", tags=["admin"])
    # BE-04: per-tenant query API.
    app.include_router(v1_router, prefix="/v1", tags=["query"])
    # BE-05: per-tenant MCP-over-HTTP endpoint. Single URL; tenant is
    # resolved from the API key, not the path. See docs/architecture/v1.md §5.
    app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])

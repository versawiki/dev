"""Router registration.

Add a new top-level router by importing it here and appending it to
``register_routers``. Keep nested router trees (e.g. ``admin/``) in
their own subpackages.
"""

from __future__ import annotations

from fastapi import FastAPI

from .admin import admin_router
from .health import router as health_router


def register_routers(app: FastAPI) -> None:
    """Mount every router onto the app.

    Order is cosmetic only (it affects OpenAPI tag grouping).
    """
    app.include_router(health_router)
    app.include_router(admin_router, prefix="/v1/admin", tags=["admin"])

    # Future ticket mount points (intentional comments — keep when filling in):
    # from .tenants import router as tenants_router  # BE-04
    # app.include_router(tenants_router, prefix="/v1/tenants", tags=["tenants"])
    # from ..mcp.router import router as mcp_router  # BE-05
    # app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])

"""Admin surface. Routers mounted under ``/v1/admin``.

These endpoints will eventually require an API key with the ``admin``
scope (see ``deps.admin_key_required``). For now they accept the dev/
test bypass so the skeleton is exercisable.
"""

from __future__ import annotations

from fastapi import APIRouter

from .tenants import router as tenants_router

admin_router = APIRouter()
admin_router.include_router(tenants_router)

__all__ = ["admin_router"]

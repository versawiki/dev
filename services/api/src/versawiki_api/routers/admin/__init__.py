"""Admin surface. Routers mounted under ``/v1/admin``.

These endpoints require an API key with the ``admin`` scope (see
``deps.admin_key_required``). Tests install a fixture-issued admin
key via ``conftest.admin_auth_headers``.
"""

from __future__ import annotations

from fastapi import APIRouter

from .api_keys import router as api_keys_router
from .tenants import router as tenants_router

admin_router = APIRouter()
admin_router.include_router(tenants_router)
admin_router.include_router(api_keys_router)

__all__ = ["admin_router"]

"""Versioned ``/v1`` router group.

These are the routes humans (web/desktop/mobile) call. The MCP
endpoint (BE-05) reuses the same query path internally but exposes a
JSON-RPC-shaped wrapper at ``/mcp``.

All routes in this group:

- Require an :class:`ApiKey` (via ``api_key_required``).
- Enforce the cross-tenant guard: the key's ``tenant_id`` MUST equal
  the path ``tenant_id``. Mismatch -> 403 ``tenant_scope_mismatch``.
- Resolve the tenant via :func:`get_tenant_session`, which opens an
  :class:`AsyncSession` bound to ``vw_<slug>`` (or a stub session in
  test/dev).
"""

from __future__ import annotations

from fastapi import APIRouter

from .ontology import router as ontology_router
from .pages import router as pages_router
from .query import router as query_router

v1_router = APIRouter()
v1_router.include_router(query_router)
v1_router.include_router(pages_router)
v1_router.include_router(ontology_router)

__all__ = ["v1_router"]

"""Tenant admin routes (stub bodies).

Persistence is BE-03's job. Today these return shape-correct stub
responses so the OpenAPI contract is stable and client codegen
already works.

Contract notes for downstream tickets:
- A tenant's ``slug`` is the URL-safe identifier used everywhere
  (schema name = ``vw_<slug>``, MCP URL = ``/t/<slug>/mcp`` if we
  ever go path-based).
- ``id`` is a server-issued opaque string (UUIDv7 in BE-03).
- ``db_schema_name`` is informational on the wire and is *not*
  client-controllable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, status

from ...deps import AdminApiKey
from ...errors import TenantNotFound
from ...schemas.common import PaginatedList, PaginationParamsDep
from ...schemas.tenant import CreateTenantRequest, TenantOut

router = APIRouter(prefix="/tenants")


def _stub_tenant(slug: str, display_name: str | None = None) -> TenantOut:
    return TenantOut(
        id=str(uuid.uuid4()),
        slug=slug,
        display_name=display_name or slug.replace("-", " ").title(),
        plan="free",
        db_schema_name=f"vw_{slug}",
        created_at=datetime.now(timezone.utc),
    )


@router.post(
    "",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant (stub).",
    description=(
        "Stub implementation. Returns a shape-correct TenantOut without "
        "persisting anything. BE-03 wires the real persistence + schema "
        "provisioner."
    ),
)
def create_tenant(
    payload: CreateTenantRequest,
    _admin: AdminApiKey,
) -> TenantOut:
    return _stub_tenant(slug=payload.slug, display_name=payload.display_name)


@router.get(
    "",
    response_model=PaginatedList[TenantOut],
    summary="List tenants (stub).",
    description="Stub implementation. Returns an empty page.",
)
def list_tenants(
    pagination: PaginationParamsDep,
    _admin: AdminApiKey,
) -> PaginatedList[TenantOut]:
    return PaginatedList[TenantOut](
        items=[],
        total=0,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantOut,
    summary="Get a tenant by id (stub).",
    description="Stub implementation. Always 404s; BE-03 wires lookup.",
    responses={404: {"description": "Tenant not found."}},
)
def get_tenant(
    tenant_id: str,
    _admin: AdminApiKey,
) -> TenantOut:
    # Until BE-03 wires persistence we cannot resolve any id. We always
    # respond with a structured 404 so clients can rely on the error
    # envelope shape.
    raise TenantNotFound(
        message="Tenant lookup is not implemented yet.",
        details={"tenant_id": tenant_id},
    )

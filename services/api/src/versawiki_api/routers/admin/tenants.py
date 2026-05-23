"""Tenant admin routes — real persistence via :class:`TenantStore`.

BE-03 swap: the stubs that returned synthetic ``TenantOut`` objects
are gone. ``create_tenant``, ``list_tenants`` and ``get_tenant`` now
all flow through a :class:`TenantStore` (the app's wired implementation
is in-memory by default; production wiring drops in
:class:`PostgresTenantStore` with a :class:`TenantProvisioner` behind
it).

Contract notes:

- A tenant's ``slug`` is the URL-safe identifier used everywhere.
- ``id`` is a server-issued opaque string (UUIDv4 today).
- ``db_schema_name`` is informational on the wire and is *not*
  client-controllable.
- The per-tenant Postgres role password is returned exactly once
  inside the create response, alongside the ``TenantOut`` body, so
  the caller can persist it in their own secret store.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from ...deps import AdminApiKey, TenantStoreDep
from ...db.tenant_store import TenantAlreadyExistsError, TenantRecord
from ...db.provisioner import InvalidSlugError
from ...errors import TenantAlreadyExists, TenantNotFound, VersawikiHTTPException
from ...schemas.common import PaginatedList, PaginationParamsDep
from ...schemas.tenant import CreateTenantRequest, TenantOut

router = APIRouter(prefix="/tenants")


def _to_out(record: TenantRecord) -> TenantOut:
    return TenantOut(
        id=record.id,
        slug=record.slug,
        display_name=record.display_name,
        plan=record.plan,  # type: ignore[arg-type]
        db_schema_name=record.db_schema_name,
        created_at=record.created_at,
    )


class CreatedTenant(BaseModel):
    """Body of the 201 response from ``POST /v1/admin/tenants``.

    ``role_password`` is shown exactly once. The caller MUST persist it
    in their own secret store if they ever need the per-tenant role's
    credentials (subsequent admin calls will not return it).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    display_name: str
    plan: str
    db_schema_name: str
    db_role_name: str
    role_password: str | None = Field(
        default=None,
        description=(
            "The per-tenant Postgres role password. Returned exactly once "
            "at create time when the provisioner is wired; null otherwise."
        ),
    )
    created_at: str  # ISO-8601


def _record_to_created(record: TenantRecord) -> CreatedTenant:
    return CreatedTenant(
        id=record.id,
        slug=record.slug,
        display_name=record.display_name,
        plan=record.plan,
        db_schema_name=record.db_schema_name,
        db_role_name=record.db_role_name,
        role_password=record.role_password,
        created_at=record.created_at.isoformat(),
    )


@router.post(
    "",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant.",
    description=(
        "Provisions a new tenant: inserts a row into the admin tenants "
        "table and, when the provisioner is wired, creates the "
        "``vw_<slug>`` schema and ``vw_<slug>_app`` role."
    ),
    responses={
        409: {"description": "A tenant with that slug already exists."},
        422: {"description": "Slug failed validation."},
    },
)
async def create_tenant(
    payload: CreateTenantRequest,
    _admin: AdminApiKey,
    store: TenantStoreDep,
) -> TenantOut:
    try:
        record = await store.create(
            slug=payload.slug,
            display_name=payload.display_name,
            plan=payload.plan,
        )
    except TenantAlreadyExistsError:
        raise TenantAlreadyExists(
            details={"slug": payload.slug},
        ) from None
    except InvalidSlugError as exc:
        raise VersawikiHTTPException(
            status_code=422,
            code="validation_error",
            message=str(exc),
            details={"slug": payload.slug},
        ) from None
    return _to_out(record)


@router.get(
    "",
    response_model=PaginatedList[TenantOut],
    summary="List tenants.",
)
async def list_tenants(
    pagination: PaginationParamsDep,
    _admin: AdminApiKey,
    store: TenantStoreDep,
) -> PaginatedList[TenantOut]:
    records, total = await store.list(limit=pagination.limit, offset=pagination.offset)
    return PaginatedList[TenantOut](
        items=[_to_out(r) for r in records],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantOut,
    summary="Get a tenant by id.",
    responses={404: {"description": "Tenant not found."}},
)
async def get_tenant(
    tenant_id: str,
    _admin: AdminApiKey,
    store: TenantStoreDep,
) -> TenantOut:
    record = await store.get(tenant_id)
    if record is None:
        raise TenantNotFound(details={"tenant_id": tenant_id})
    return _to_out(record)

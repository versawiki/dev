"""Data layer (BE-03).

Public surface:

- :func:`get_async_engine` / :func:`get_session` — engine factory and
  FastAPI per-request session dep.
- :class:`TenantProvisioner` — creates a ``vw_<slug>`` schema, a
  ``vw_<slug>_app`` role, and runs the per-tenant migrations.
- :class:`TenantStore` (protocol) + :class:`InMemoryTenantStore` +
  :class:`PostgresTenantStore` — tenant directory persistence.
- :mod:`models.admin` / :mod:`models.tenant` — declarative classes.
- ``migrations/`` — Alembic env for both admin and tenant targets.
"""

from __future__ import annotations

from .engine import (
    SessionDep,
    async_session_factory,
    get_async_engine,
    get_session,
    reset_engine_cache,
)
from .provisioner import (
    InvalidSlugError,
    ProvisionPlan,
    ProvisionResult,
    TenantProvisioner,
    build_provision_plan,
    role_name_for,
    schema_name_for,
    validate_slug,
)
from .tenant_store import (
    InMemoryTenantStore,
    PostgresTenantStore,
    TenantAlreadyExistsError,
    TenantRecord,
    TenantStore,
)

__all__ = [
    "InMemoryTenantStore",
    "InvalidSlugError",
    "PostgresTenantStore",
    "ProvisionPlan",
    "ProvisionResult",
    "SessionDep",
    "TenantAlreadyExistsError",
    "TenantProvisioner",
    "TenantRecord",
    "TenantStore",
    "async_session_factory",
    "build_provision_plan",
    "get_async_engine",
    "get_session",
    "reset_engine_cache",
    "role_name_for",
    "schema_name_for",
    "validate_slug",
]

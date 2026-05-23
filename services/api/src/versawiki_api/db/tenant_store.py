"""Tenant directory store: protocol + in-memory + Postgres impls.

Mirrors the :class:`ApiKeyStore` pattern: the admin routes depend on
a protocol, and the app wires whichever implementation it wants.

- :class:`InMemoryTenantStore` — the default. Used by tests and dev
  runtime so the admin endpoints work without a Postgres dependency.
  The provisioner is optional; if absent, ``create`` skips the
  schema/role step and only records the tenant in memory.
- :class:`PostgresTenantStore` — real production implementation;
  inserts into ``vw_admin.tenants`` and (always) runs the provisioner.

Construction-time injection of the provisioner keeps this module
free of any subprocess concerns and lets unit tests pass a stub.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models.admin import Tenant as TenantRow
from .provisioner import (
    ProvisionResult,
    TenantProvisioner,
    role_name_for,
    schema_name_for,
    validate_slug,
)


@dataclass(frozen=True)
class TenantRecord:
    """Domain object — what the admin route hands back to clients.

    ``role_password`` is populated exactly once, at create time. It is
    NOT included in ``list`` or ``get`` results. The caller (admin
    route) decides whether to surface it.
    """

    id: str
    slug: str
    display_name: str
    plan: str
    db_schema_name: str
    db_role_name: str
    created_at: datetime
    role_password: str | None = None
    opt_out_signature_sharing: bool = False


class TenantAlreadyExistsError(ValueError):
    """Raised when ``create`` is called with a slug that already exists."""


@runtime_checkable
class TenantStore(Protocol):
    async def create(
        self,
        *,
        slug: str,
        display_name: str,
        plan: str = "free",
    ) -> TenantRecord:
        """Provision a new tenant. Slug must be unique."""
        ...

    async def get(self, tenant_id: str) -> TenantRecord | None:
        """Return a tenant by id, or ``None``."""
        ...

    async def get_by_slug(self, slug: str) -> TenantRecord | None:
        """Return a tenant by slug, or ``None``."""
        ...

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TenantRecord], int]:
        """List tenants. Returns (items, total)."""
        ...

    async def set_opt_out(
        self,
        tenant_id: str,
        *,
        opt_out_signature_sharing: bool,
    ) -> TenantRecord | None:
        """Toggle the opt-out flag. Returns the updated record or None if tenant missing."""
        ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------

@dataclass
class _InMemoryRow:
    record: TenantRecord


class InMemoryTenantStore:
    """In-process tenant store. The default for tests and dev runtime.

    Optionally takes a :class:`TenantProvisioner` so an integration
    test (or a dev environment with a real Postgres but the in-memory
    admin store) can still exercise the schema/role step. When the
    provisioner is ``None``, ``create`` returns a record with no
    ``role_password`` and no real schema is created.
    """

    def __init__(self, provisioner: TenantProvisioner | None = None) -> None:
        self._by_id: dict[str, _InMemoryRow] = {}
        self._by_slug: dict[str, _InMemoryRow] = {}
        self._provisioner = provisioner
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        slug: str,
        display_name: str,
        plan: str = "free",
    ) -> TenantRecord:
        validate_slug(slug)
        async with self._lock:
            if slug in self._by_slug:
                raise TenantAlreadyExistsError(slug)

            if self._provisioner is not None:
                result = await self._provisioner.provision(slug)
                schema = result.schema
                role = result.role
                role_password: str | None = result.role_password
            else:
                schema = schema_name_for(slug)
                role = role_name_for(slug)
                role_password = None

            record = TenantRecord(
                id=str(uuid.uuid4()),
                slug=slug,
                display_name=display_name,
                plan=plan,
                db_schema_name=schema,
                db_role_name=role,
                created_at=datetime.now(timezone.utc),
                role_password=role_password,
                opt_out_signature_sharing=False,
            )
            row = _InMemoryRow(record=record)
            self._by_id[record.id] = row
            self._by_slug[record.slug] = row
            return record

    async def get(self, tenant_id: str) -> TenantRecord | None:
        row = self._by_id.get(tenant_id)
        return None if row is None else _strip_password(row.record)

    async def get_by_slug(self, slug: str) -> TenantRecord | None:
        row = self._by_slug.get(slug)
        return None if row is None else _strip_password(row.record)

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TenantRecord], int]:
        records = [_strip_password(r.record) for r in self._by_id.values()]
        records.sort(key=lambda r: r.created_at)
        total = len(records)
        return records[offset : offset + limit], total

    async def set_opt_out(
        self,
        tenant_id: str,
        *,
        opt_out_signature_sharing: bool,
    ) -> TenantRecord | None:
        async with self._lock:
            row = self._by_id.get(tenant_id)
            if row is None:
                return None
            current = row.record
            # TenantRecord is frozen=True, so rebuild and reassign.
            updated = TenantRecord(
                id=current.id,
                slug=current.slug,
                display_name=current.display_name,
                plan=current.plan,
                db_schema_name=current.db_schema_name,
                db_role_name=current.db_role_name,
                created_at=current.created_at,
                role_password=current.role_password,
                opt_out_signature_sharing=opt_out_signature_sharing,
            )
            row.record = updated
            # The slug index points to the same _InMemoryRow object, so
            # it sees the mutation through ``row.record`` automatically.
            return _strip_password(updated)


# ---------------------------------------------------------------------------
# Postgres implementation
# ---------------------------------------------------------------------------

class PostgresTenantStore:
    """Postgres-backed tenant directory. Provisioner is mandatory here."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        provisioner: TenantProvisioner,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._provisioner = provisioner

    @staticmethod
    def _row_to_record(row: TenantRow) -> TenantRecord:
        return TenantRecord(
            id=row.id,
            slug=row.slug,
            display_name=row.display_name,
            plan=row.plan,
            db_schema_name=row.db_schema_name,
            db_role_name=row.db_role_name,
            created_at=row.created_at,
            role_password=None,
            opt_out_signature_sharing=row.opt_out_signature_sharing,
        )

    async def create(
        self,
        *,
        slug: str,
        display_name: str,
        plan: str = "free",
    ) -> TenantRecord:
        validate_slug(slug)
        # Pre-check (cheap; we still rely on the unique constraint for
        # the race-loser case).
        existing = await self.get_by_slug(slug)
        if existing is not None:
            raise TenantAlreadyExistsError(slug)

        result = await self._provisioner.provision(slug)
        async with self._sessionmaker() as session, session.begin():
            row = TenantRow(
                id=str(uuid.uuid4()),
                slug=slug,
                display_name=display_name,
                plan=plan,
                db_schema_name=result.schema,
                db_role_name=result.role,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            record = self._row_to_record(row)
        return TenantRecord(
            id=record.id,
            slug=record.slug,
            display_name=record.display_name,
            plan=record.plan,
            db_schema_name=record.db_schema_name,
            db_role_name=record.db_role_name,
            created_at=record.created_at,
            role_password=result.role_password,
            opt_out_signature_sharing=record.opt_out_signature_sharing,
        )

    async def get(self, tenant_id: str) -> TenantRecord | None:
        async with self._sessionmaker() as session:
            stmt = select(TenantRow).where(TenantRow.id == tenant_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else self._row_to_record(row)

    async def get_by_slug(self, slug: str) -> TenantRecord | None:
        async with self._sessionmaker() as session:
            stmt = select(TenantRow).where(TenantRow.slug == slug)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else self._row_to_record(row)

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TenantRecord], int]:
        async with self._sessionmaker() as session:
            count_stmt = select(func.count()).select_from(TenantRow)
            total = (await session.execute(count_stmt)).scalar_one()
            stmt = (
                select(TenantRow)
                .order_by(TenantRow.created_at)
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._row_to_record(r) for r in rows], int(total)

    async def set_opt_out(
        self,
        tenant_id: str,
        *,
        opt_out_signature_sharing: bool,
    ) -> TenantRecord | None:
        async with self._sessionmaker() as session, session.begin():
            stmt = (
                update(TenantRow)
                .where(TenantRow.id == tenant_id)
                .values(opt_out_signature_sharing=opt_out_signature_sharing)
            )
            result = await session.execute(stmt)
            if result.rowcount == 0:
                return None
            row = (
                await session.execute(
                    select(TenantRow).where(TenantRow.id == tenant_id),
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._row_to_record(row)


def _strip_password(record: TenantRecord) -> TenantRecord:
    """Return a copy of ``record`` with ``role_password`` cleared."""
    if record.role_password is None:
        return record
    return TenantRecord(
        id=record.id,
        slug=record.slug,
        display_name=record.display_name,
        plan=record.plan,
        db_schema_name=record.db_schema_name,
        db_role_name=record.db_role_name,
        created_at=record.created_at,
        role_password=None,
        opt_out_signature_sharing=record.opt_out_signature_sharing,
    )


__all__ = [
    "InMemoryTenantStore",
    "PostgresTenantStore",
    "TenantAlreadyExistsError",
    "TenantRecord",
    "TenantStore",
]

"""Declarative models for the ``vw_admin`` (control-plane) schema.

This schema is the singleton — there's exactly one ``vw_admin`` per
Postgres database and it stores cross-tenant rows: the tenant
directory and the API keys that authenticate against it.

Tables here are **not** rendered into a per-tenant schema. Anything
per-tenant lives in :mod:`.tenant`.

Cross-references:

- ``docs/architecture/v1.md`` § 2 (data model sketch).
- ``DECISIONS.md`` 2026-05-22 (schema-per-tenant, with the admin
  schema as a shared control plane).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ADMIN_SCHEMA = "vw_admin"


class AdminBase(DeclarativeBase):
    """Base for everything under the ``vw_admin`` schema.

    The shared :class:`MetaData` is schema-pinned, so every subclass
    table lands inside ``vw_admin`` without each ``__table_args__``
    repeating the schema name.
    """

    metadata = MetaData(schema=ADMIN_SCHEMA)


class Tenant(AdminBase):
    """A versawiki tenant.

    The ``slug`` is the URL-safe identifier used everywhere (it
    becomes part of the per-tenant schema name and the per-tenant
    Postgres role). It's immutable for the lifetime of the tenant.
    """

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    db_schema_name: Mapped[str] = mapped_column(String(64), nullable=False)
    db_role_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # M1-MCP-05: per-tenant opt-out for signature sharing. When True,
    # the meta-MCP collector drops every envelope from this tenant
    # before anything reaches the meta store. The API-surface name is
    # the more explicit ``opt_out_signature_sharing``; the meta-mcp's
    # ``TenantSignatureConfig`` exposes the same value under ``opt_out``.
    opt_out_signature_sharing: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa.false(),
        default=False,
    )

    api_keys: Mapped[list["ApiKeyRow"]] = relationship(
        "ApiKeyRow",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )


class ApiKeyRow(AdminBase):
    """An issued API key.

    The wire token is ``vw_<prefix>_<secret>``. We store the prefix
    in clear (it's safe to log) and only the argon2 hash of the
    secret. ``last_used_at`` is touched in a single UPDATE statement
    on lookup — see :class:`PostgresApiKeyStore`.
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("prefix", name="uq_api_keys_prefix"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(f"{ADMIN_SCHEMA}.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scopes: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="api_keys")


__all__ = [
    "ADMIN_SCHEMA",
    "AdminBase",
    "Tenant",
    "ApiKeyRow",
]

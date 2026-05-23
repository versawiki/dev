"""Alembic environment.

Two modes, selected by environment variable:

- ``VW_MIGRATION_TARGET=admin``  — operate on the shared ``vw_admin``
  schema. ``target_metadata`` is :data:`AdminBase.metadata`.
  ``version_locations`` is the ``versions/admin`` directory.

- ``VW_MIGRATION_TARGET=tenant`` — operate on a per-tenant schema.
  ``VW_TENANT_SCHEMA`` must be set to the schema name (``vw_<slug>``).
  ``target_metadata`` is :data:`TenantBase.metadata`, and the
  connection's ``search_path`` is set to the tenant schema for the
  duration of the migration. ``version_locations`` is
  ``versions/tenant``.

The Alembic version table itself is created **inside the target
schema** so each per-tenant schema carries its own migration history
(no cross-tenant table contention) and the admin schema carries its
own.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure the package is importable.
import sys
_THIS = Path(__file__).resolve()
_SRC = _THIS.parents[3]  # services/api/src
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from versawiki_api.db.models.admin import AdminBase, ADMIN_SCHEMA  # noqa: E402
from versawiki_api.db.models.tenant import TenantBase  # noqa: E402

# Alembic Config object — values from alembic.ini.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_target() -> str:
    target = os.environ.get("VW_MIGRATION_TARGET", "").lower().strip()
    if target not in {"admin", "tenant"}:
        raise RuntimeError(
            "VW_MIGRATION_TARGET must be 'admin' or 'tenant'. Got: "
            f"{target!r}",
        )
    return target


def _resolve_tenant_schema(target: str) -> str | None:
    if target != "tenant":
        return None
    schema = os.environ.get("VW_TENANT_SCHEMA", "").strip()
    if not schema:
        raise RuntimeError(
            "VW_MIGRATION_TARGET=tenant requires VW_TENANT_SCHEMA to be set.",
        )
    if not schema.startswith("vw_"):
        raise RuntimeError(
            "VW_TENANT_SCHEMA must start with 'vw_'. Got: " + repr(schema),
        )
    return schema


def _resolve_database_url() -> str:
    url = os.environ.get("VW_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("VW_DATABASE_URL must be set for migrations.")
    return url


def _version_locations_for(target: str) -> str:
    base = _THIS.parent / "versions" / target
    return str(base)


TARGET = _resolve_target()
TENANT_SCHEMA = _resolve_tenant_schema(TARGET)
DATABASE_URL = _resolve_database_url()

config.set_main_option("script_location", str(_THIS.parent))
config.set_main_option("version_locations", _version_locations_for(TARGET))
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = AdminBase.metadata if TARGET == "admin" else TenantBase.metadata
version_table_schema = ADMIN_SCHEMA if TARGET == "admin" else TENANT_SCHEMA


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=version_table_schema,
        include_schemas=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Set search_path for tenant migrations so unqualified table
        # references hit the tenant schema. Admin migrations explicitly
        # qualify every table with ``vw_admin.`` via the schema-pinned
        # MetaData.
        if TARGET == "tenant":
            connection.exec_driver_sql(f'SET search_path TO "{TENANT_SCHEMA}"')

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=version_table_schema,
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

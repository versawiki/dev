"""Alembic migration tree.

The directory layout intentionally splits per-target version folders so
the admin (singleton) schema and the per-tenant (one-per-customer)
schemas evolve independently:

- ``versions/admin/`` — DDL for the shared ``vw_admin`` schema.
  Migration target is selected by ``VW_MIGRATION_TARGET=admin``.
- ``versions/tenant/`` — DDL for the per-tenant schemas. Migration
  target is selected by ``VW_MIGRATION_TARGET=tenant`` plus
  ``VW_TENANT_SCHEMA=vw_<slug>``.

The shared :mod:`env` script reads those env vars and points Alembic
at the right ``script_location`` + ``target_metadata``.
"""

from __future__ import annotations

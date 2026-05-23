"""SQLAlchemy ORM models, partitioned by schema.

- :mod:`admin` — the singleton ``vw_admin`` schema (control plane).
- :mod:`tenant` — per-tenant schema templates (one schema per tenant
  at runtime; the declarative classes here just describe the table
  shape).

Each module exports its own ``Base`` so Alembic's per-schema migration
runs only see the tables they're meant to manage.
"""

from __future__ import annotations

# `versawiki_api.db`

Data layer for the versawiki API. Shipped by BE-03.

## Modules

- `engine.py` — async SQLAlchemy engine factory + per-request session
  dep (`get_session` / `SessionDep`).
- `provisioner.py` — `TenantProvisioner`. Validates the slug, creates
  the `vw_<slug>` schema and `vw_<slug>_app` role, grants USAGE +
  CREATE, then invokes Alembic to stamp the per-tenant tables.
- `tenant_store.py` — `TenantStore` protocol + `InMemoryTenantStore`
  (default for tests/dev) and `PostgresTenantStore` (production).
- `models/admin.py` — declarative models for the `vw_admin` schema:
  `Tenant`, `ApiKeyRow`.
- `models/tenant.py` — declarative models for the five per-tenant stub
  tables (`documents`, `chunks`, `pages`, `ontology_nodes`,
  `query_log`). Stub columns; ING-02 and ING-04 fill in real ones
  (pgvector + HNSW, ontology features).
- `migrations/` — Alembic env supporting two targets via
  `VW_MIGRATION_TARGET`:
  - `admin` → `versions/admin/` (singleton `vw_admin` schema).
  - `tenant` → `versions/tenant/` (per-tenant; reads `VW_TENANT_SCHEMA`).

## Running migrations

```bash
# Admin schema
VW_MIGRATION_TARGET=admin \
VW_DATABASE_URL=postgresql+psycopg://localhost/versawiki \
PYTHONPATH=src \
  alembic -c alembic.ini upgrade head

# A specific tenant schema (the provisioner does this automatically)
VW_MIGRATION_TARGET=tenant \
VW_TENANT_SCHEMA=vw_acme \
VW_DATABASE_URL=postgresql+psycopg://localhost/versawiki \
PYTHONPATH=src \
  alembic -c alembic.ini upgrade head
```

## Cross-references

- `docs/architecture/v1.md` § 2 (data model sketch) and § 4 (auth /
  tenant isolation).
- `DECISIONS.md` 2026-05-22: "Tenant isolation = schema-per-tenant".

## Notes

- The `chunks.embedding` column is presently a JSON stub. ING-02 swaps
  it to `vector(1024)` (HNSW indexed; dimension locked in DECISIONS).
- `vw_admin` is the shared control plane schema; everything else is
  one-schema-per-tenant.
- Tests run against `InMemoryTenantStore` so no Postgres is required.
  Integration tests under `tests/integration/` exercise the real
  provisioner when `VW_TEST_DATABASE_URL` is set.

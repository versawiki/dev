# `versawiki_api.db`

Placeholder. The data layer (BE-03 in `BACKLOG.md`) will live here.

## What goes here

- `engine.py` — SQLAlchemy 2.0 engine factory keyed on settings.
- `session.py` — `sessionmaker` + the real `get_db_session` FastAPI
  dependency (replaces the stub in `versawiki_api.deps`).
- `tenant.py` — schema provisioner. `CREATE SCHEMA vw_<slug>`,
  `CREATE ROLE vw_role_<slug>`, `GRANT USAGE`, and the per-request
  `SET search_path` / `SET ROLE` dance from
  `docs/architecture/v1.md` § 4.4.
- `models/` — SQLAlchemy ORM classes:
  - `admin.py` — shared `vw_admin` schema (`tenants`, `api_keys`).
  - `tenant.py` — per-tenant tables (`sources`, `documents`,
    `chunks`, `ontology_nodes`, `wiki_pages`, `query_log`).
- `alembic/` — migration env (per-schema fan-out).

## Cross-references

- `docs/architecture/v1.md` § 2 (data model sketch) and § 4 (auth /
  tenant isolation).
- `DECISIONS.md` 2026-05-22: "Tenant isolation = schema-per-tenant".
- `BACKLOG.md` M1-BE-03.

## Notes for BE-03

- The `chunks.embedding` column is `vector(1024)` — dimension is
  locked per `DECISIONS.md` 2026-05-22 embedding entry.
- HNSW index, not IVFFlat (same decisions doc).
- The `vw_admin` schema is shared; everything else is per-tenant.

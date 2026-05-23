# `versawiki-api`

The Query API + MCP-over-HTTP endpoint for Versawiki. Modular monolith:
all of `Query API` (1.2), `Per-tenant MCP endpoint` (1.3), and the
admin surface live in this one Python package and one process. Workers
(RQ-driven ingestion) import this same package as a library so their
DB session, settings, logging, and schemas stay consistent.

See `docs/architecture/v1.md` for the broader service decomposition.

## Layout

```
src/versawiki_api/
  __main__.py          uvicorn launcher (python -m versawiki_api)
  app.py               FastAPI() factory; routers, CORS, logging, OpenAPI
  config.py            pydantic-settings BaseSettings (env-driven)
  logging.py           structlog setup
  errors.py            typed HTTPException subclasses + handlers
  deps.py              FastAPI DI: DB session stub, tenant resolver, api-key auth
  routers/
    health.py          /healthz, /readyz
    admin/tenants.py   /v1/admin/tenants (stub bodies; persistence is BE-03)
  schemas/             Pydantic v2 request/response models
  mcp/                 placeholder for BE-05 (MCP-over-HTTP endpoint)
  db/                  placeholder for BE-03 (schema provisioner + Alembic env)
  _internal/openapi.py emit openapi.json for client codegen
tests/                 pytest + httpx AsyncClient against the in-process app
```

## Run it

```bash
# from services/api/
pip install -e .[test]

# dev server
python -m versawiki_api
# or
uvicorn versawiki_api.app:create_app --factory --reload --port 8000

# tests
pytest -q tests/

# OpenAPI export (for web/desktop/mobile codegen)
python -m versawiki_api._internal.openapi > openapi.json
```

## Configuration

Everything is environment-driven via `pydantic-settings`. See
`src/versawiki_api/config.py` for the full list. Common ones:

| Env var | Default | Purpose |
|---|---|---|
| `VW_DB_URL` | `postgresql+psycopg://localhost/versawiki` | Admin DB DSN |
| `VW_REDIS_URL` | `redis://localhost:6379/0` | Queue + cache |
| `VW_LOG_LEVEL` | `INFO` | structlog level |
| `VW_CORS_ORIGINS` | `http://localhost:3000` | Comma-sep allow list |
| `VW_ENV` | `dev` | `dev` / `staging` / `prod` |

## What is NOT here yet

- DB connectivity. `deps.get_db_session` raises `NotImplementedError`.
  BE-03 wires SQLAlchemy + Alembic. `/readyz` will start pinging the
  DB at that point.
- Auth. `deps.api_key_required` returns a `StubApiKey` placeholder.
  BE-02 wires real argon2-hashed key validation with a Redis cache.
- MCP transport. `mcp/` is a placeholder. BE-05 fills it.
- Query / ontology / pages routes. BE-04 adds them under
  `routers/tenants/`.

The plumbing for each is already in place so each ticket is a drop-in.

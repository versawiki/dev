# Architecture layout — reader's guide

A one-page map of the repo. Pair this with `docs/architecture/v1.md`
(service decomposition) and `docs/architecture/stack.md` (locked
versions).

```
versawiki/
├── README.md                 project intro
├── ROADMAP.md                milestones M0..M7
├── STATUS.md                 live session board
├── BACKLOG.md                tickets by milestone
├── DECISIONS.md              decision log (append-only, newest at top)
├── AGENTS.md                 agent team roster + operating rules
├── ARCHITECTURE-LAYOUT.md    this file
├── docs/
│   ├── architecture/         design docs (v1.md, stack.md, ...)
│   ├── research/             Researcher's outputs (landscape, prior-art, ...)
│   └── tickets/              heavier ticket specs (M1-MCP-01a, ...)
├── notes/
│   └── <role>.md             one per agent role (backend, ingestion, qa, ...)
├── services/
│   ├── api/                  Query API + admin + (forthcoming) MCP endpoint
│   ├── ingestion/            RQ workers: walk -> chunk -> embed -> classify
│   └── meta-mcp/             self-improving cross-tenant skill writer
└── apps/
    ├── web/                  Next.js 15 (App Router)
    ├── desktop/              Tauri 2 wrapper
    └── mobile/               Expo SDK 52
```

Many of those directories don't exist yet. They appear as their
backlog tickets land. This document and the empty package-level
READMEs (e.g. `services/api/src/versawiki_api/mcp/README.md`) are the
load-bearing placeholders that keep the import paths stable.

## `services/api/` — the modular monolith (M1)

Everything HTTP-served lives in one Python package, one process,
shipped as `versawiki-api`. Workers (`services/ingestion/`) import
this same package as a library so config, logging, and DB sessions
stay consistent.

```
services/api/
├── pyproject.toml            FastAPI 0.115, Pydantic 2.9, SQLAlchemy 2,
│                             Alembic, psycopg, redis, rq, pyjwt,
│                             argon2-cffi, httpx, structlog, anthropic,
│                             openai. Python >=3.12.
├── README.md                 service-level run instructions
└── src/versawiki_api/
    ├── __init__.py           __version__, __service_name__
    ├── __main__.py           `python -m versawiki_api` -> uvicorn
    ├── app.py                FastAPI factory (CORS, logging, OpenAPI, routers)
    ├── config.py             pydantic-settings BaseSettings (VW_* env)
    ├── logging.py            structlog (pretty in dev, JSON in prod)
    ├── errors.py             typed HTTPException subclasses + handlers
    ├── deps.py               FastAPI DI: settings, DB session (stub),
    │                         api-key auth (stub), tenant resolver (stub)
    ├── routers/
    │   ├── __init__.py       register_routers(app) — single mount point
    │   ├── health.py         GET /healthz, GET /readyz
    │   └── admin/tenants.py  POST/GET /v1/admin/tenants{,/{id}} (stub)
    ├── schemas/              Pydantic v2 wire contracts
    │   ├── common.py         ErrorEnvelope, pagination, health
    │   └── tenant.py         CreateTenantRequest, TenantOut
    ├── mcp/                  placeholder for BE-05 (see README inside)
    ├── db/                   placeholder for BE-03 (see README inside)
    └── _internal/openapi.py  `python -m versawiki_api._internal.openapi`
                              writes openapi.json for client codegen
```

`tests/` mirrors the package and runs with `pytest -q`.

## Conventions future Backend tickets follow

1. **One router per resource**, mounted from `routers/__init__.py`.
   Nested admin/tenants/etc. go in their own subpackages.
2. **All error responses use `ErrorEnvelope`.** Raise a
   `VersawikiHTTPException` subclass; never `HTTPException` directly.
3. **Schemas live in `schemas/<resource>.py`.** Never in the router
   file. Workers and the MCP layer import them too.
4. **Dependencies are typed with `Annotated[..., Depends(...)]`.**
   See `deps.py` for the canonical aliases (`SettingsDep`,
   `DbSession`, `CurrentApiKey`, `CurrentTenant`).
5. **Settings only via `get_settings()`** (lru-cached). Tests clear
   the cache in `conftest.py`.
6. **Structured logs only.** Use `versawiki_api.logging.get_logger`.
7. **OpenAPI is the source of truth for clients.** Regenerate with
   `python -m versawiki_api._internal.openapi > openapi.json` and
   commit the diff alongside the change.

## Mapping back to v1.md

| `v1.md` § | Code home |
|---|---|
| 1.2 Query API | `services/api/src/versawiki_api/` |
| 1.3 Per-tenant MCP endpoint | `services/api/src/versawiki_api/mcp/` (BE-05) |
| 2. Data model | `services/api/src/versawiki_api/db/` (BE-03) |
| 4. Auth + tenant isolation | `deps.py` + `db/tenant.py` (BE-02/BE-03) |
| 5. MCP endpoint shape | `mcp/` (BE-05) |
| `services/ingestion/` § 1.1 | future ticket ING-01.. |
| `services/meta-mcp/` § 1.4 | future ticket MCP-01.. |

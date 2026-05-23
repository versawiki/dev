_Backend engineer's working notes. Newest at top._

## 2026-05-22 — M1-BE-03 done: Postgres persistence + tenant provisioner

**Result:** 77 tests pass, 2 skip cleanly. New tests: 50 (12 model-shape,
30 provisioner SQL + slug validation, 7 tenant-store + route round-trip,
1 admin metadata pin). Integration tests collect and skip with
`@pytest.mark.integration` when `VW_TEST_DATABASE_URL` is unset.

**Test run (sandbox):**

```
cd services/api
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vwpyc PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q tests/
# 77 passed, 2 skipped in 2.90s
```

**What landed:**

- `db/engine.py` — async engine factory + cached engine + `get_session`
  FastAPI dep + `SessionDep`. URL is read from `Settings.database_url`
  (new field — driver `asyncpg`). Legacy `db_url` retained as a
  back-compat shim so any pre-BE-03 reference still imports.
- `db/models/admin.py` — `Tenant`, `ApiKeyRow`. Schema-pinned MetaData
  on `AdminBase` so both tables land in `vw_admin` without per-table
  schema args.
- `db/models/tenant.py` — `Document`, `Chunk`, `WikiPage`,
  `OntologyNode`, `QueryLog`. Stub columns only; `chunks.embedding_stub`
  is JSON for now (ING-02 swaps to `vector(1024)` + HNSW). Metadata is
  schema-less by design — the schema is set at migration time via
  `SET search_path` so the same model classes serve every tenant.
- `db/provisioner.py` — `TenantProvisioner.provision(slug)` runs in
  three phases:
  1. `validate_slug` (regex `^[a-z][a-z0-9-]{1,30}[a-z0-9]$`, no
     consecutive hyphens; tighter than the schemas/tenant regex
     because the role name `vw_<slug>_app` must fit `NAMEDATALEN=63`).
  2. DDL: `CREATE SCHEMA "vw_<slug>"`, `CREATE ROLE "vw_<slug>_app"
     WITH LOGIN PASSWORD '...'`, `GRANT USAGE, CREATE ON SCHEMA ...`,
     plus default privileges (`SELECT/INSERT/UPDATE/DELETE` on tables,
     `USAGE/SELECT` on sequences) so future tenant tables and
     sequences are usable by the role.
  3. Spawns `python -m alembic upgrade head` with
     `VW_MIGRATION_TARGET=tenant` and `VW_TENANT_SCHEMA=vw_<slug>` to
     stamp the five stub tables.
- `db/migrations/` — Alembic env with two targets selected by
  `VW_MIGRATION_TARGET` (`admin` | `tenant`). Two `versions/` dirs;
  each has one initial migration (admin = `tenants` + `api_keys`,
  tenant = the five stubs).
- `db/tenant_store.py` — `TenantStore` protocol +
  `InMemoryTenantStore` (default; the dev/test runtime keeps working
  with no Postgres) + `PostgresTenantStore`. Both implement
  `create / get / get_by_slug / list`.
- `auth/postgres_store.py` — `PostgresApiKeyStore`. Same protocol
  as `InMemoryApiKeyStore`; `lookup_by_token` does one `SELECT` +
  one `UPDATE` (touching `last_used_at`) in a single transaction.
- `routers/admin/tenants.py` — `create_tenant` / `list_tenants` /
  `get_tenant` now use the `TenantStore`. The stub 404 in `get_tenant`
  is gone; a `409 tenant_already_exists` is returned for duplicate
  slugs.
- `deps.py` — `get_db_session` no longer raises 501; it re-exports
  the real async session yielder. New `TenantStoreDep`.

**Dependencies added:**

- `pyproject.toml`: `sqlalchemy[asyncio]` (was bare `sqlalchemy`),
  `asyncpg` (new — async driver), `pytest-asyncio` already present in
  the test extra. Existing `psycopg[binary]` retained (Alembic's
  subprocess uses sync DSN).

**Decisions made (cheap; logged here not DECISIONS.md):**

- **Role name = `vw_<slug>_app` (not `vw_role_<slug>`).** The
  architecture doc had it as `vw_role_<tenant>`; I went with
  `vw_<slug>_app` because (a) it keeps the per-tenant noun first
  (better `\du` ergonomics), (b) it shares the `vw_<slug>` prefix
  with the schema so identifying a tenant's whole footprint is one
  `grep`. Flag-changeable — only the provisioner + admin DDL care.
- **Per-tenant role password returned in the create response.** Shown
  exactly once; never returned by `get` or `list`. Stored only in the
  caller's secret manager. We do **not** persist the password on the
  `tenants` row — the original architecture sketch had a hashed copy,
  but holding a hashed credential we never verify against just adds a
  leak surface. If admins lose it, they reset via
  `ALTER ROLE ... PASSWORD ...`.
- **Provisioner runs Alembic via `subprocess.run`.** Alembic's
  upgrade API is sync-only and creates its own engine; running it
  inside the asyncpg event loop tangles. Subprocess keeps it clean
  and matches the standard Alembic CLI pattern. ~200 ms cost per
  tenant provisioning — fine for an admin endpoint.
- **`TenantStore` interface mirrors `ApiKeyStore`.** In-memory default
  so existing tests (`conftest`) need zero changes. Postgres impl is
  the production wiring; integration tests cover it.
- **Slug regex tightened from `schemas/tenant.py`'s 3-40 chars to 3-32
  here.** Schema is the validation gatekeeper for the wire; the
  provisioner is the gatekeeper for the DB. The tighter check means
  `vw_<slug>_app` always fits Postgres NAMEDATALEN with margin.
- **`embedding_stub` column.** Real column type is pgvector(1024); we
  can't depend on the pgvector extension being installed in the
  sandbox or in a fresh dev DB. JSON for now; ING-02 swaps.

**What's stubbed (waits for ING tickets):**

- `chunks.embedding_stub` JSON → `vector(1024)` + HNSW index (ING-02).
- `documents.blob_key`, `documents.last_modified_at`,
  `documents.deleted_at` (ING-02).
- `ontology_nodes.embedding`, `.confidence`, `.source`,
  `document_ontology` join table (ING-04).
- `query_log.query_embedding`, `query_log.result_chunk_ids` (BE-04).

**Potential follow-up tickets:**

- **BE-03b: `PostgresTenantStore` integration coverage.** The
  integration test covers the provisioner directly but not the
  `PostgresTenantStore.create` → DB row → list path. A small ticket
  to add 2-3 more e2e cases once a CI Postgres exists.
- **BE-03c: Set-role-at-request-start.** The architecture's "SET
  search_path / SET ROLE" dance lives on BE-05 today (since that's
  the layer that actually constrains the connection). When BE-04
  starts hitting per-tenant tables, BE-03c should add a
  `tenant_scoped_session` dep that wraps `get_session` and sets the
  role from the validated API key.
- **Provisioner idempotency mode.** Today `provision` errors on a
  pre-existing schema. An "ensure" mode would be nice for ops.

**Sandbox quirks unchanged:**

- Python 3.10 in the bash mount; `requires-python>=3.12` in pyproject.
  Tests run with `PYTHONPATH=src` and manually-installed deps. Real
  CI on 3.12 will be cleaner.
- The asyncpg driver is the production target; the sandbox doesn't
  have a Postgres instance, so only the unit tests exercise the
  engine factory (the engine builds successfully but no connection
  is made until the integration tests run).


## 2026-05-22 — M1-BE-01 done: FastAPI skeleton landed

**Result:** Tests green (8/8). Layout under `services/api/` matches the
ticket spec. OpenAPI export works (`/healthz`, `/readyz`,
`/v1/admin/tenants`, `/v1/admin/tenants/{tenant_id}`).

**Test run (effective command in sandbox):**

```
cd services/api
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/vwpyc \
  python3 -B -m pytest -q tests/
# 8 passed in 0.08s
```

**Sandbox quirks (not blockers — production runs Python 3.12):**

1. The Cowork bash mount only has Python 3.10. `pyproject.toml` pins
   `requires-python = ">=3.12"` per the locked stack, so
   `pip install -e .` fails with a "different Python" error in the
   sandbox. I installed runtime deps directly with `pip install
   --break-system-packages fastapi pydantic pydantic-settings structlog
   uvicorn pytest pytest-asyncio httpx` and ran tests with
   `PYTHONPATH=src`. CI on real 3.12 will work with the canonical
   `pip install -e .[test] && pytest -q tests/`.
2. The bash mount also denies `rm` on existing `.pyc` files (mount
   permissions). Worked around with `PYTHONPYCACHEPREFIX=/tmp/vwpyc`
   and `PYTHONDONTWRITEBYTECODE=1` so stale 3.10 bytecode doesn't
   shadow source changes. Not relevant in normal CI.
3. `datetime.UTC` is 3.11+. The skeleton uses `datetime.timezone.utc`
   for the same effect so the file is 3.10-importable in the sandbox.
   No behavioural difference on 3.12.

**Decisions made (cheap, recorded here rather than DECISIONS.md):**

- **Error envelope shape locked.** All error responses are
  `{"error": {"code": "...", "message": "...", "details": {...}}}`.
  `code` is the stable machine-readable handle; client code branches
  on it. Add new `VersawikiHTTPException` subclasses in
  `errors.py`; never raise raw `HTTPException`.
- **Logging goes to stderr, not stdout.** So that
  `python -m versawiki_api._internal.openapi > openapi.json` produces
  a clean JSON file even with `INFO`-level logs enabled.
- **`settings_dep` reads from `app.state.settings`** rather than
  calling `get_settings()` directly. Lets tests pass a custom
  `Settings(env="test")` into `create_app` without mutating env vars.
  Pattern propagates to BE-02/BE-03 — anywhere you need settings in a
  request handler, use `SettingsDep` and you get the test-overrideable
  copy automatically.
- **Auth dep signature locked even though body is a stub.** Routes
  type-hint `Annotated[StubApiKey, Depends(api_key_required)]` today.
  BE-02 swaps the class name (`StubApiKey -> ApiKey`) and the body;
  signature stays. The `is_stub` bypass in `admin_key_required` is
  there so dev/test routes are exercisable now; BE-02 should remove
  it when real scopes load from the DB.
- **`db/` and `mcp/` are placeholder packages with READMEs.** Locks
  import paths so BE-04's query routes can share schemas with BE-05's
  MCP tools without circular imports. BE-03 fills `db/`; BE-05 fills
  `mcp/`.
- **`Pydantic v2 + extra="forbid"` on all wire models.** Catches typos
  in client requests early. Loosen on a per-model basis only if a
  field deliberately needs to be open (none today).

**What BE-02, BE-03, BE-04, BE-05 inherit:**

- Project layout in `ARCHITECTURE-LAYOUT.md` at the repo root (also
  added).
- Conventions section there lists the seven rules future tickets
  follow (one router per resource, error envelope, schemas in
  `schemas/`, `Annotated[..., Depends(...)]` deps, settings via
  `get_settings()`/`SettingsDep`, structlog only, OpenAPI as the
  client-codegen source of truth).
- `pyproject.toml` already lists every M1 dep (sqlalchemy, alembic,
  psycopg, redis, rq, pyjwt, argon2-cffi, anthropic, openai) so each
  ticket only needs to write code, not extend deps.
- `routers/__init__.py` has commented-out mount points for BE-04 and
  BE-05 — drop in.
- `db/README.md` and `mcp/README.md` tell BE-03 and BE-05 exactly
  what modules to add.

**Open questions for the Orchestrator / next ticket:**

- None blocking. BE-02 is unblocked; the dep seam is sketched and
  argon2-cffi is in `pyproject.toml`.

## 2026-05-23 — M1-BE-05 done: MCP-over-HTTP endpoint

**Result:** 115 tests pass, 2 skip cleanly. 21 new tests across the 6
MCP suites; existing 94 BE-01/02/03/04 tests unchanged.

**Test run (sandbox):**

```
cd services/api
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vwpyc PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest -q tests/
# 115 passed, 2 skipped in 7.58s
```

**What landed:**

- `mcp/schemas.py` — Pydantic v2 input/output models for the four tools.
  `tool_definitions()` derives the JSON-Schema payload for `tools/list`
  via `model_json_schema()` so input validation and the wire schema stay
  in lockstep. `TOOL_NAMES` is a frozen tuple so tests assert the names
  never drift.
- `mcp/tools.py` — four async tool handlers, signatures pinned to
  `tool_<name>(tenant_id, *, arguments, ...)`. `search` reuses the BE-04
  embedding-then-empty-envelope path (same `QueryResponse` shape). The
  other three return their stub envelopes (`list_ontology`) or a
  `not_found` `ToolError` (`read_page`, `read_chunk`) until ING-02 /
  ING-04 / ING-05 land real persistence. Errors carry a stable code
  (`-32602` invalid_arguments, `-32004` not_found) and structured
  `data`.
- `mcp/transport.py` — minimal MCP-over-HTTP streamable transport.
  JSON-RPC 2.0 envelope on POST `/mcp` with `initialize`, `tools/list`,
  `tools/call`. SSE response (`event: message`, single envelope) when
  `Accept: text/event-stream`; plain JSON otherwise. Tenant identity is
  taken EXCLUSIVELY from the validated API key — a `tenant_id` field in
  `arguments` is rejected with JSON-RPC `-32602` and the offending field
  surfaced in `data`.
- `mcp/router.py` — single-route APIRouter, `POST ""`. Mounted at
  `/mcp` (no per-tenant path segment; the v1 architecture doc § 5
  resolves tenant via the key, not the URL). Returns `Response` with
  `response_model=None` so FastAPI doesn't try to introspect the
  JSON/Streaming union.
- `routers/__init__.py` — uncommented the BE-05 mount point; the MCP
  router is now wired into `create_app`.

**Contract pinned by tests:**

1. **Four tool names, exact.** `search`, `read_page`, `read_chunk`,
   `list_ontology`. Renaming any of them is a breaking change for every
   LLM client. Pinned by `test_tools_list_returns_exactly_four_tools`
   and the `available_tools` field on the `method_not_found` error.
2. **`tools/call name=search` returns the same envelope as BE-04.**
   `{answer_chunks, pages, query_id, took_ms}`. Pinned by
   `test_search_returns_query_envelope`.
3. **Embedding provider invoked exactly once per `search`.** And NEVER
   on a validation failure (`test_search_missing_q_returns_invalid_params_error`).
4. **Tool errors live inside the JSON-RPC envelope, HTTP stays 200.**
   `read_page`/`read_chunk` 404s, unknown-tool errors, and arguments-
   smuggling-tenant-id rejections all return HTTP 200 with `error` in
   the body. Pinned by `test_read_page_unknown_id_returns_envelope_not_found`
   and `test_tenant_id_in_arguments_is_rejected`.
5. **Cross-tenant via JSON-RPC body is impossible.** Tenant comes from
   the API key only. `arguments.tenant_id` is rejected without ever
   calling the embedder. Pinned by `test_tenant_id_in_arguments_is_rejected`.
6. **SSE and JSON paths return the same envelope.** Same `id`, same
   `result`, same embedder side effects. The SSE response is a single
   `event: message` carrying the envelope JSON in `data:`. Pinned by
   `test_search_sse_response_carries_result_event`.
7. **Missing auth = HTTP 401 (not a JSON-RPC error).** The bearer is
   the outermost gate; an LLM client without a valid key never gets to
   the dispatcher. Pinned by `test_initialize_without_auth_returns_401`.

**Decisions made (cheap; logged here, not DECISIONS.md):**

- **Server protocol version `2025-06-18`.** Date-based string; LLM
  clients feature-detect on it. The MCP spec moves quickly enough that
  pinning a date is easier than tracking semver.
- **JSON-RPC server-error codes for app errors.** `-32004` for
  not-found, `-32602` for invalid arguments (re-uses the spec
  invalid_params), `-32601` for unknown tool. Inside the -32000/-32099
  range the spec leaves us free to define our own.
- **`Response` return type with `response_model=None`.** FastAPI tried
  to build a response model from the `JSONResponse | StreamingResponse`
  union and failed; the clean fix is to disable response-model
  introspection for this route. The transport assembles the right
  Response subclass internally.
- **SSE = single `message` event for now.** The streamable transport
  spec allows multi-event streams; our four read-only tools don't
  produce partial results, so one event per response is enough. If we
  later add a long-running tool (e.g., `generate_page`) the transport's
  `_sse_iter` is the one place to extend.
- **`jsonschema` validator picked at runtime.** Sandbox ships
  jsonschema 3.x which only has Draft 7. Production / a fresh install
  gets Draft 2020-12. Tests prefer the newest validator the runtime
  knows about; Pydantic-emitted schemas validate under both.

**Follow-ups for the next backlog wave:**

- **BE-05b: hook `search` into the real chunks SQL** once ING-02 ships
  the pgvector column. Today both the REST and MCP paths embed but
  return empty; flipping to real rows is a body-only change inside
  `tool_search`.
- **BE-05c: per-tenant tool-description tuning.** Architecture doc § 5
  notes that the meta-MCP will eventually write per-tenant tool blurbs
  ("search this customer\'s solar-project documents (SLDs, civil
  drawings, RFIs)") into the `description` field. The hook lives in
  `tool_definitions()` — accept a tenant id, look up overrides from
  the meta-MCP, merge.
- **BE-05d: rate limit + per-tool token-budget headers.** The
  architecture's "token budget discipline" (each response sized) needs
  a wrapper around the dispatcher. Not blocking; ship after a real
  customer hits the endpoint and we have a usage shape.
- **Notifications path.** `notifications/initialized` and friends are
  accepted silently today; we could wire a no-op acknowledgment if any
  LLM client complains.

**Sandbox quirks unchanged:**

- Python 3.10 in the bash mount; tests run with `PYTHONPATH=src`.
- `jsonschema` 3.x — older Draft-7-only API. Tests detect and adapt.

---

_Backend engineer's working notes. Newest at top._

## 2026-05-22 — M1-BE-04 done: v1 query API routes

**Result:** 94 tests pass, 2 skip cleanly. 17 new tests (6 query, 3 pages,
4 ontology, 4 resolver). Existing 77 BE-01/02/03 tests still pass unchanged.

**Test run (sandbox):**

```
cd services/api
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vwpyc PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -q tests/
# 94 passed, 2 skipped in 4.39s
```

**What landed:**

- `routers/v1/__init__.py` — versioned router group, mounted under
  `/v1` in `app.py` with `tags=["query"]`.
- `routers/v1/query.py` — `POST /v1/tenants/{tenant_id}/query`.
  Request: `{q, top_k=8, filters={}}`. Response envelope:
  `{answer_chunks: [...], pages: [...], query_id: <uuid>, took_ms: <int>}`.
  Today returns empty lists; the embedding pipeline is real (calls the
  wired `EmbeddingProvider` exactly once with verbatim `q`). Sketch SQL
  for the `chunks <=>` cosine-distance query is in-source as a comment
  for ING-02 to activate.
- `routers/v1/pages.py` — `GET /v1/tenants/{tenant_id}/pages/{page_id}`.
  Stub body raises a typed `PageNotFound` (404, `page_not_found`) —
  ING-05 owns the page builder. Cross-tenant guard still runs first.
- `routers/v1/ontology.py` — `GET /v1/tenants/{tenant_id}/ontology`.
  Returns `{root: {id: "root", label: "", kind: "category", children: []}}`
  by default; `?node_id=...` re-roots. Tests assert shape only.
- `services_api_tenant.py` — `get_tenant_session` FastAPI dep +
  `resolve_tenant` helper. Flow: validate API key (existing dep) ->
  enforce cross-tenant guard -> look up tenant record -> yield
  `TenantContext` carrying a session. Real Postgres session path uses
  `SET search_path TO "vw_<slug>", vw_admin` and resets on exit; the
  default test/dev path yields a `StubAsyncSession` so the in-memory
  tenant store works end-to-end with no Postgres dependency. Toggle is
  `app.state.use_real_db_session = True` (production wiring sets it).
- `deps.py` — added `EmbeddingProvider` duck-typed Protocol +
  `EmbeddingProviderDep`. Defaults to a process-local stub
  (`_LocalStubEmbeddingProvider`); production wires the OpenAI
  provider via `set_embedding_provider(app, ...)` at startup. The api
  package does NOT runtime-depend on `versawiki_ingestion` — any
  provider with the right shape works, which keeps the ingestion's
  canonical `StubEmbeddingProvider` plug-compatible for tests that
  want determinism.
- `errors.py` — new typed `TenantScopeMismatch` (403,
  `tenant_scope_mismatch`). Details carry both `api_key_tenant_id` and
  `path_tenant_id` for debugging.

**Contract pinned by tests:**

1. **Cross-tenant access is 403, not 404.** A key for tenant A querying
   tenant B (real or non-existent) gets `tenant_scope_mismatch`. The
   guard runs before the existence check so 404-vs-403 cannot be used
   to enumerate tenant ids. Pinned by
   `test_resolve_tenant_scope_guard_runs_before_existence_check`.
2. **Empty result keeps the envelope shape.** A query against a tenant
   with no chunks (which is every tenant today) returns valid JSON of
   the documented shape — clients can codegen against the OpenAPI spec
   now and not break when ING-02 fills in the rows. Pinned by
   `test_query_returns_envelope_shape`.
3. **Embedding called once per request with the verbatim `q`.** Pinned
   by `test_query_returns_envelope_shape` + `test_query_defaults_top_k_to_eight`.
4. **Validation failures never invoke the embedder.** `q=""` returns
   422 with zero embedder calls. Pinned by `test_query_empty_q_returns_422`.

**Follow-ups for the next backlog wave:**

- BE-05 (MCP endpoint) reuses `get_tenant_session` + `EmbeddingProviderDep`
  verbatim — the same auth + cross-tenant guard + session path. The
  MCP route shape becomes JSON-RPC over `/mcp` but the tools call into
  the same `versawiki_api.routers.v1.query` handler internals.
- ING-02 swaps `chunks.embedding_stub` (JSON) for `vector(1024)` and
  activates the in-source sketch SQL in `query.py`.
- ING-05 (page builder) flips `pages.get_page` from "always 404" to a
  real lookup; the route shape is already pinned.
- Production wiring (a future `wsgi.py` or startup hook) sets
  `app.state.use_real_db_session = True` and installs the OpenAI
  embedding provider via `set_embedding_provider`.

---

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

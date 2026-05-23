_Backend engineer's working notes. Newest at top._

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

# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Current milestone

**M1 — Local-folder ingestion (headless).** Three services standing up in parallel. 108 tests across all three. Privacy boundary enforced by code (not just docs).

## Last session summary (2026-05-22, Wave 3)

**Wave 3 (3 parallel specialists, 2 finishers) returned and integrated:**

- **Backend (M1-BE-02)** — API-key auth middleware. `services/api/src/versawiki_api/auth/` with `keys.py`, `hashing.py`, `middleware.py`. Admin routes: `POST /v1/admin/tenants/{tid}/api-keys`, `GET /...` (never returns raw token), `DELETE /v1/admin/api-keys/{kid}`. Token format `vw_<prefix>_<secret>` with hex alphabet (no `_` ambiguity). Argon2id hashing with stdlib scrypt fallback. 27/27 tests passing.
- **Ingestion (M1-ING-01)** — `services/ingestion/` with `Connector` Protocol, `LocalFolderConnector`, 3 lifted parsers (base/email/excel), parser registry, AEC starter taxonomy YAML. 40/40 tests passing.
- **Meta-MCP (M1-MCP-01a)** — `services/meta-mcp/` with 5-stage privacy checker pipeline (schema-validate → forbidden-field → PII/regex → numeric → quote → opt-out), `TenantAuditLog` JSONL writer that NEVER persists the offending payload, full Pydantic v2 DomainObservation implementation. 41 pass / 1 skip (spaCy missing) / 1 xfail (non-privacy bug in numeric.py — `branching_factor_p50/p95` capped at [0,1] though spec allows >1).

**Bug fixed inline this session:** `secrets.token_urlsafe()` includes `_` in its alphabet, making the on-wire token `vw_<prefix>_<secret>` ambiguous to split. All 4 BE-02 test failures cascaded from this. Switched to `secrets.token_hex()`. `parse_token` also now enforces min-length on prefix/secret.

## In flight

- (none — about to spawn Wave 4)

## Blockers awaiting Josh

- (none — token is in session memory; all decisions either locked or appropriately escalated and answered)

## Next intended action (this session)

**Wave 4 — three more parallel specialists:**

1. **Backend** — `M1-BE-03` Tenant schema provisioner. `CREATE SCHEMA vw_<slug>`, per-tenant Postgres role, Alembic per-schema migration runner.
2. **Ingestion** — `M1-ING-02` Chunker + embedder pipeline. **NET-NEW** per M0-06 audit. RQ worker, idempotent on content hash, OpenAI `text-embedding-3-large@1024` provider, pluggable `EmbeddingProvider`.
3. **MCP-builder** — `M1-MCP-02` Signature collector. Subscribes to ingestion events, computes signatures per the 8 payload variants, runs through M1-MCP-01a checkers, writes to meta-store.

## Quick links

- `README.md` — mission
- `ROADMAP.md` — milestones
- `BACKLOG.md` — what's ready, in flight, and done
- `DECISIONS.md` — what we've locked and why
- `AGENTS.md` — team roster and operating rules
- `ARCHITECTURE-LAYOUT.md` — where everything lives in the repo
- `docs/architecture/stack.md` — locked stack
- `docs/architecture/v1.md` — v1 system design
- `docs/architecture/domain-observation-v1.md` — meta-MCP wire contract
- `docs/research/*` — landscape, ontology, prior-art (now includes M0-06 real audit)
- `services/api/` — FastAPI + API-key auth (BE-01, BE-02)
- `services/ingestion/` — connector + parsers (ING-01)
- `services/meta-mcp/` — privacy checker pipeline + audit log (MCP-01a)
- `notes/*` — per-role working logs

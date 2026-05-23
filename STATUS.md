# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Current milestone

**M1 — Local-folder ingestion (headless).** 273 tests passing across three services. Postgres provisioner + chunker/embedder pipeline + privacy-gated signature collector all in place.

## Last session summary (2026-05-22, Wave 4)

**Wave 4 (3 parallel specialists) returned and integrated:**

- **Backend (M1-BE-03 — 77/77, +50 new)** — Real Postgres provisioner. `db/{engine,provisioner,tenant_store}.py`, `db/models/{admin,tenant}.py`, Alembic env supporting two targets (`admin` and `tenant` schemas), `auth/postgres_store.py`. Provisioner: `CREATE SCHEMA "vw_<slug>"` + per-tenant role + grants + Alembic upgrade. Slug regex prevents SQL injection. 2 integration tests skip cleanly when no `VW_TEST_DATABASE_URL` set; unit tests cover SQL generation directly.
- **Ingestion (M1-ING-02 — 90/90, +50 new)** — Chunker + embedder. `chunking/` (RecursiveCharacterSplitter, hierarchical `[\n\n, \n, ". ", " ", ""]`, idempotent content_hash), `embedding/` (Protocol + StubEmbeddingProvider + OpenAIEmbeddingProvider hitting `text-embedding-3-large` at 1024 dim via Matryoshka), `pipeline/process_document.py` end-to-end. EMBEDDING_DIM=1024 enforced at every layer.
- **Meta-MCP (M1-MCP-02 — 106/108, +65 new)** — Signature collector. 8 `compute_*` functions (one per payload variant) all using bucket/ratio outputs only. `SignatureCollector` orchestrates raw event → compute signature → wrap envelope → run M1-MCP-01a CheckerPipeline → persist via `FileMetaStore` OR write rejection to `TenantAuditLog`. Single `_COMPUTE_DISPATCH` table; no alternate code path. Fixed 2 source bugs in MCP-01a along the way (UUID-vs-phone false positive; Python 3.10 `datetime.fromisoformat` Z-suffix tolerance).

**Total tests now: 273 passing** (api 77 + ingestion 90 + meta-mcp 106) + 4 cleanly-skipping (sandbox env).

## In flight

- (none — Wave 4 just landed)

## Blockers awaiting Josh

- (none)

## Next intended action (Wave 5 candidates)

Three independent paths still parallel-safe:

1. **Backend** — `M1-BE-04` Query API routes (`/query`, `/pages`, `/ontology`) wired to the per-tenant DB session.
2. **Ingestion** — `M1-ING-03` Document classifier (LLM-based, with confidence + uncertainty signal piped to meta-MCP).
3. **MCP-builder** — `M1-MCP-03` Skill writer (threshold-triggered LLM job that writes domain-pattern skills to `services/meta-mcp/skills/<domain>/`, runs MCP-01a checkers on the text, commits to git).

## Quick links

- `README.md`, `ROADMAP.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, `ARCHITECTURE-LAYOUT.md`
- `docs/architecture/{stack,v1,domain-observation-v1}.md`
- `docs/research/{landscape,ontology,prior-art}.md`
- `services/api/` — FastAPI + auth + Postgres provisioner (BE-01, BE-02, BE-03)
- `services/ingestion/` — connector + parsers + chunker/embedder pipeline (ING-01, ING-02)
- `services/meta-mcp/` — privacy checker pipeline + audit log + signature collector + meta-store (MCP-01a, MCP-02)
- `notes/*` — per-role working logs

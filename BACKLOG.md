# Backlog

Prioritized top-to-bottom within each section. The Orchestrator pulls from "Ready" when spawning specialists. Items become "In flight" when a specialist is working on them, "Done" when merged.

Each ticket: `ID — title (role) — one-line description`. Heavier specs go in `docs/tickets/<id>.md`.

## Ready (M1 — Wave 4 candidates, all parallel-safe)

**Backend / API**

- `M1-BE-03 — Tenant schema provisioner (Backend)` — `CREATE SCHEMA vw_<slug>`; Alembic per-schema migration runner; per-tenant Postgres role with GRANT/REVOKE. SQLAlchemy 2.x async engine. Wire the real `db/` package under `services/api/`; the stub placeholder is already there.
- `M1-BE-04 — Query API routes (Backend)` — `POST /v1/tenants/{tid}/query`, `GET /pages/{pid}`, `GET /ontology`. Mostly stubs at first.
- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)` — `search`, `read_page`, `read_chunk`, `list_ontology` tools. Streamable transport. Lives under `services/api/src/versawiki_api/mcp/` (placeholder already in place).

**Ingestion**

- `M1-ING-02 — Chunker + embedder pipeline (Ingestion) — FULLY NET-NEW` — Per M0-06 surprise: build from scratch. RQ worker, idempotent on content hash. `EmbeddingProvider` abstraction; OpenAI `text-embedding-3-large@1024` as the M1 provider. Stub provider for tests (no real API calls).
- `M1-ING-03 — Document classifier (Ingestion)` — LLM-based (Claude primary), with confidence + uncertainty signal piped to the meta-MCP for skill-write decisions.
- `M1-ING-04 — Ontology inducer (Ingestion)` — BERTopic clustering + LLM-proposed taxonomy + Leiden community detection. Bootstraps from the AEC starter taxonomy.
- `M1-ING-05 — Wiki page builder (Ingestion)` — Stale-on-event materialisation; one page per ontology node + per cluster.
- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)` — Tracks query patterns; queues re-cluster/re-page jobs when distributions shift.

**Meta-MCP**

- `M1-MCP-02 — Signature collector (MCP-builder)` — Subscribes to ingestion events, computes anonymized structural signatures per the 8 payload variants, runs through M1-MCP-01a checkers, writes to the meta-tenant store. Async event loop + persistence.
- `M1-MCP-03 — Skill writer (MCP-builder)` — Threshold-triggered LLM job that writes domain-pattern skill markdowns to `services/meta-mcp/skills/<domain>/`, runs MCP-01a checkers on the generated text, and commits via the team git pipeline for auditability.
- `M1-MCP-04 — Skill applier (MCP-builder)` — Prepends matching skill text to ingestion prompts when a tenant's signature matches a known domain.
- `M1-MCP-05 — Per-tenant opt-out (MCP-builder)` — Tenant-level flag to disable even principle-sharing. Honored by signature collector and skill applier.

**QA**

- `M1-QA-01 — End-to-end smoke harness (QA)` — Ingest a small sample folder, run a query, see pages, hit the MCP endpoint, get tools back. Lives in `tests/e2e/`.
- `M1-QA-02 — Tenant-isolation property tests (QA)` — Forced cross-tenant calls must fail; per-tenant role enforcement must hold.
- `M1-QA-03 — Privacy-boundary property tests (QA)` — Generate synthetic `DomainObservation` payloads containing customer-specific names/figures/quotes; assert the static checkers reject every one.

## In flight

- (none — Wave 3 just landed)

## Done

- `M1-MCP-01a — Privacy static checkers (MCP-builder)` — `services/meta-mcp/` with 5-stage pipeline + tenant audit log. 41 passing / 1 skip / 1 xfail. Audit log never persists offending payload (privacy invariant test green).
- `M1-ING-01 — Connector interface + local-folder connector (Ingestion)` — `services/ingestion/` with Connector Protocol, LocalFolderConnector, 3 lifted parsers, AEC starter taxonomy YAML. 40/40 tests passing.
- `M1-BE-02 — API-key auth middleware (Backend)` — argon2 hashing, hex token format, admin issue/list/revoke routes, raw token returned once. 27/27 tests passing including conftest bug fix (token_urlsafe -> token_hex eliminates `_` ambiguity).
- `M1-BE-01 — FastAPI skeleton (Backend)` — locked downstream patterns (error envelope, settings_dep, auth dep seam).
- `M1-MCP-01 — DomainObservation event schema (Architect)` — 561-line spec, 8 payload variants, discriminated union.
- `M0-06 — Audit prior MCP-server repo (Researcher)` — file-by-file table (3 REUSE / 11 ADAPT / 13 REPLACE).
- `M0-05 — Catalog prior MCP-server code (Researcher)` — superseded by M0-06.
- `M0-04 — Survey ontology-induction approaches (Researcher)`.
- `M0-03 — Survey existing file-storage-to-wiki products (Researcher)`.
- `M0-02 — Draft v1 system design (Architect)`.
- `M0-01 — Recommend tech stack (Architect)`.

## Icebox (not yet prioritized)

- Cross-customer pattern sharing protocol (M7)
- Mobile read-only viewer (M5)
- Billing & API key issuance UI
- Desktop "private mode" embedded Python ingestion (M3)
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6)

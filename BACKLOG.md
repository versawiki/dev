# Backlog

Prioritized top-to-bottom within each section. The Orchestrator pulls from "Ready" when spawning specialists.

Each ticket: `ID — title (role) — one-line description`.

## Ready (M1 — Wave 5 candidates, all parallel-safe)

**Backend / API**

- `M1-BE-04 — Query API routes (Backend)` — `POST /v1/tenants/{tid}/query`, `GET /pages/{pid}`, `GET /ontology`. Wire to per-tenant DB session via the BE-03 provisioner. Tools call the embedding pipeline (ING-02) for query embedding.
- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)` — `search`, `read_page`, `read_chunk`, `list_ontology` tools. Streamable transport. Reuses the BE-04 query path internally.

**Ingestion**

- `M1-ING-03 — Document classifier (Ingestion)` — LLM-based (Claude primary), confidence + uncertainty signal piped to meta-MCP for skill-write decisions. Bootstraps from `services/ingestion/seeds/aec_starter_taxonomy.yaml`.
- `M1-ING-04 — Ontology inducer (Ingestion)` — BERTopic + LLM-proposed taxonomy + Leiden community detection over the embedded chunks.
- `M1-ING-05 — Wiki page builder (Ingestion)` — Stale-on-event materialisation; one page per ontology node + per cluster.
- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)` — Tracks query patterns; queues re-cluster/re-page jobs when distributions shift.

**Meta-MCP**

- `M1-MCP-03 — Skill writer (MCP-builder)` — Threshold-triggered LLM job that writes domain-pattern skill markdowns to `services/meta-mcp/skills/<domain>/`, runs MCP-01a checkers on the generated text, and commits via the team git pipeline for auditability.
- `M1-MCP-04 — Skill applier (MCP-builder)` — Prepends matching skill text to ingestion prompts when a tenant's signature matches a known domain.
- `M1-MCP-05 — Per-tenant opt-out (MCP-builder)` — Tenant-level flag UI/API (the gate is already honored by the collector and applier).

**QA**

- `M1-QA-01 — End-to-end smoke harness (QA)` — Ingest a small sample folder, run a query, see pages, hit the MCP endpoint.
- `M1-QA-02 — Tenant-isolation property tests (QA)` — Cross-tenant calls must fail; per-tenant role enforcement holds.
- `M1-QA-03 — Privacy-boundary property tests (QA)` — Adversarial DomainObservation payloads must always be rejected.

## In flight

- (none — Wave 4 just landed)

## Done

- `M1-MCP-02 — Signature collector (MCP-builder)` — `services/meta-mcp/{events,collector,store}/`. 8 compute_* functions, gated by MCP-01a pipeline. 65 new tests (106 total in service).
- `M1-ING-02 — Chunker + embedder pipeline (Ingestion)` — `services/ingestion/{chunking,embedding,pipeline}/`. RecursiveCharacterSplitter, EmbeddingProvider Protocol with Stub + OpenAI impls at 1024 dim. 50 new tests (90 total).
- `M1-BE-03 — Tenant schema provisioner (Backend)` — `services/api/src/versawiki_api/db/`. SQL-injection-safe CREATE SCHEMA + role + grants + Alembic. 50 new tests (77 total).
- `M1-MCP-01a — Privacy static checkers (MCP-builder)` — 5-stage pipeline + tenant audit log.
- `M1-ING-01 — Connector interface + local-folder connector (Ingestion)`.
- `M1-BE-02 — API-key auth middleware (Backend)`.
- `M1-BE-01 — FastAPI skeleton (Backend)`.
- `M1-MCP-01 — DomainObservation event schema (Architect)`.
- `M0-06 — Audit prior MCP-server repo (Researcher)`.
- `M0-01..05 — All M0 tickets done`.

## Icebox (not yet prioritized)

- M1-BE-03b — PostgresTenantStore integration coverage (needs CI Postgres).
- M1-BE-03c — Per-request `SET ROLE` / `search_path` dep (deferred until BE-04 hits per-tenant tables).
- M1-MCP-01a-fix — branching_factor xfail (numeric.py overly strict on [0,1] for real values >1).
- Cross-customer pattern sharing protocol (M7).
- Mobile read-only viewer (M5).
- Billing & API key issuance UI.
- Desktop "private mode" embedded Python ingestion (M3).
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6).

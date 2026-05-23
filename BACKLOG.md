# Backlog

Prioritized top-to-bottom within each section. The Orchestrator pulls from "Ready" when spawning specialists.

## Ready (M1 — Wave 6 candidates, all parallel-safe)

**Backend / API**

- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)` — `search`, `read_page`, `read_chunk`, `list_ontology` tools. Streamable transport. Reuses `get_tenant_session` + `EmbeddingProviderDep` verbatim.

**Ingestion**

- `M1-ING-04 — Ontology inducer (Ingestion)` — BERTopic clustering + LLM-proposed taxonomy + Leiden community detection over embedded chunks. Bootstraps from AEC starter taxonomy.
- `M1-ING-05 — Wiki page builder (Ingestion)` — Stale-on-event materialisation; one page per ontology node + per cluster. Flips `pages.get_page` from always-404 to a real lookup.
- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)` — Tracks query patterns; queues re-cluster/re-page jobs when distributions shift.

**Meta-MCP**

- `M1-MCP-04 — Skill applier (MCP-builder)` — Prepends matching skill text to ingestion prompts when a tenant's signature matches a known domain.
- `M1-MCP-05 — Per-tenant opt-out (MCP-builder)` — Tenant-level flag API + UI (gate is already honored by collector and applier).

**QA**

- `M1-QA-01 — End-to-end smoke harness (QA)` — Ingest a small sample folder, run a query, see pages, hit the MCP endpoint.
- `M1-QA-02 — Tenant-isolation property tests (QA)` — Cross-tenant calls must fail; per-tenant role enforcement holds.
- `M1-QA-03 — Privacy-boundary property tests (QA)` — Adversarial DomainObservation payloads must always be rejected.

## In flight

- (none — Wave 5 just landed)

## Done

- `M1-MCP-03 — Skill writer (MCP-builder)` — Threshold-triggered LLM job; text-checker gate; version-aware file emission; git-commit hook. 35 new tests (141 total in service).
- `M1-ING-03 — Document classifier (Ingestion)` — LLM classifier with confidence + uncertainty reasons + interpretable signals. 43 new tests (133 total).
- `M1-BE-04 — Query API routes (Backend)` — v1 query/pages/ontology with tenant-scope enforcement before existence check. 17 new tests (94 total).
- `M1-MCP-02 — Signature collector (MCP-builder)`.
- `M1-ING-02 — Chunker + embedder pipeline (Ingestion)`.
- `M1-BE-03 — Tenant schema provisioner (Backend)`.
- `M1-MCP-01a — Privacy static checkers (MCP-builder)`.
- `M1-ING-01 — Connector interface + local-folder connector (Ingestion)`.
- `M1-BE-02 — API-key auth middleware (Backend)`.
- `M1-BE-01 — FastAPI skeleton (Backend)`.
- `M1-MCP-01 — DomainObservation event schema (Architect)`.
- `M0-01..06 — All M0 tickets done`.

## Icebox (not yet prioritized)

- M1-BE-03b — PostgresTenantStore integration coverage (needs CI Postgres).
- M1-BE-03c — Per-request `SET ROLE` / `search_path` dep.
- M1-MCP-01a-fix — branching_factor xfail (numeric.py overly strict on [0,1] for real values >1).
- M1-ING-03b — Classifier retry on LLM 429/5xx (currently no retries; embedder has them).
- M1-ING-03c — Taxonomy "catch-all" annotation in LLM-rendered prompt.
- Cross-customer pattern sharing protocol (M7).
- Mobile read-only viewer (M5).
- Billing & API key issuance UI.
- Desktop "private mode" embedded Python ingestion (M3).
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6).

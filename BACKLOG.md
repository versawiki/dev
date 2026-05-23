# Backlog

Prioritized top-to-bottom within each section. The Orchestrator pulls from "Ready" when spawning specialists.

## Ready (M1 — what's left, interactive priority)

**Backend** — (none remaining for M1)

**Ingestion**

- `M1-ING-05 — Wiki page builder (Ingestion)` — Stale-on-event materialisation; one page per ontology node + per cluster. Flips `pages.get_page` from always-404 to a real lookup, which then activates BE-05's `read_page` MCP tool.
- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)` — Tracks query patterns; queues re-cluster/re-page jobs when distributions shift.

**Meta-MCP**

- `M1-MCP-05 — Per-tenant opt-out (MCP-builder)` — Tenant-level flag API + persistence (gate is already honored by collector + applier; this adds the surface).

**QA** — All three on overnight safe list

- `M1-QA-01 — End-to-end smoke harness (QA)` — Ingest a small sample folder, run a query, see pages, hit the MCP endpoint.
- `M1-QA-02 — Tenant-isolation property tests (QA)` — Cross-tenant calls must fail.
- `M1-QA-03 — Privacy-boundary property tests (QA)` — Adversarial DomainObservation payloads must always be rejected.

## Overnight safe list (small scope; cron picks from here)

- `M1-ING-03b`, `M1-ING-03c`, `M1-MCP-01a-fix`, `M1-MCP-05`, `M1-QA-01`, `M1-QA-02`, `M1-QA-03`.

## In flight

- (none — Wave 6 just landed)

## Done

- `M1-MCP-04 — Skill applier (MCP-builder)` — matcher + prompt injector + cache + opt-out gate (25 new tests, 166 total in service).
- `M1-ING-04 — Ontology inducer (Ingestion)` — clusterer + LLM proposer + community detector + tree builder + merge (47 new tests, 180 total).
- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)` — JSON-RPC + SSE transport, 4 tools, tenant from API key (21 new tests, 115 total).
- `M1-MCP-03 — Skill writer (MCP-builder)` — Threshold-triggered LLM draft + text checker + version-aware emit + git commit.
- `M1-ING-03 — Document classifier (Ingestion)` — LLM classifier with confidence + uncertainty + signals.
- `M1-BE-04 — Query API routes (Backend)` — v1 query/pages/ontology, tenant-scope-before-existence.
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
- M1-BE-05b — Real chunks SQL in `tool_search` (needs pgvector activation).
- M1-MCP-04b — Real LLM matchers (current matcher is heuristic).
- Wire ING-04's OntologyInducer into a corpus-level orchestrator (no callsite yet).
- ING-03 LLM provider retry on 429/5xx (M1-ING-03b on safe list).
- ING-03 prompt `(catch-all)` annotation (M1-ING-03c on safe list).
- MCP-01a `branching_factor` numeric fix (M1-MCP-01a-fix on safe list).
- Cross-customer pattern sharing protocol (M7).
- Mobile read-only viewer (M5).
- Billing & API key issuance UI.
- Desktop "private mode" embedded Python ingestion (M3).
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6).

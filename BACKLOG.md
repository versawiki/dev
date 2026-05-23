# Backlog

Prioritized top-to-bottom within each section. The Orchestrator pulls from "Ready" when spawning specialists. Items become "In flight" when a specialist is working on them, "Done" when merged.

Each ticket: `ID — title (role) — one-line description`. Heavier specs go in `docs/tickets/<id>.md`.

## Ready (M0 — tail)

- `M0-02 — Draft v1 system design (Architect)` — Done in `docs/architecture/v1.md` but pending final ratification once Josh weighs in on the meta-MCP privacy bar. Treat as "in review."
- `M0-06 — Audit Josh's prior MCP-server repo (Researcher)` — Waiting on Josh to share the repo URL. Researcher's required file patterns are listed at the end of `docs/research/prior-art.md`.

## Ready (M1 — kicks off as soon as Josh confirms the meta-MCP privacy bar)

Dependency order, top-to-bottom. The first wave that can run in parallel is BE-01 / ING-01 / QA-shell-01.

**Backend / API**

- `M1-BE-01 — FastAPI skeleton (Backend)` — `/healthz`, `/v1/admin/tenants`, OpenAPI export, project layout under `services/api/`. Foundation for everything else.
- `M1-BE-02 — API-key auth middleware (Backend)` — Issue, hash (argon2), validate, revoke, Redis-cached lookup. Per-tenant scoping.
- `M1-BE-03 — Tenant schema provisioner (Backend)` — `CREATE SCHEMA vw_<slug>`; Alembic per-schema migration runner. Per-tenant Postgres role.
- `M1-BE-04 — Query API routes (Backend)` — `POST /v1/tenants/{tid}/query`, `GET /pages/{pid}`, `GET /ontology`. Mostly stubs at first.
- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)` — `search`, `read_page`, `read_chunk`, `list_ontology` tools. Streamable transport.

**Ingestion**

- `M1-ING-01 — Connector interface + local-folder connector (Ingestion)` — `list()`, `fetch(uri) -> bytes`, `watch() -> Iterator[ChangeEvent]`. Local-folder is the only impl in M1.
- `M1-ING-02 — Chunker + embedder pipeline (Ingestion)` — RQ worker, idempotent on content hash. `EmbeddingProvider` abstraction; OpenAI `text-embedding-3-large@1024` as the M1 provider.
- `M1-ING-03 — Document classifier (Ingestion)` — LLM-based (Claude primary), with confidence + uncertainty signal piped to the meta-MCP for skill-write decisions.
- `M1-ING-04 — Ontology inducer (Ingestion)` — BERTopic clustering + LLM-proposed taxonomy + Leiden community detection. Bootstraps from the AEC starter taxonomy.
- `M1-ING-05 — Wiki page builder (Ingestion)` — Stale-on-event materialisation; one page per ontology node + per cluster.
- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)` — Tracks query patterns; queues re-cluster/re-page jobs when distributions shift.

**Meta-MCP**

- `M1-MCP-01 — DomainObservation event schema (MCP-builder)` — The wire contract for what crosses the tenant->meta boundary. Highest-leverage single contract in the system; gets its own `docs/architecture/domain-observation-v1.md`. Blocked on Josh's privacy-bar call.
- `M1-MCP-02 — Signature collector (MCP-builder)` — Subscribes to ingestion events, computes anonymized structural signatures, writes to the meta-tenant store.
- `M1-MCP-03 — Skill writer (MCP-builder)` — Threshold-triggered LLM job that writes domain-pattern skill markdowns to `services/meta-mcp/skills/<domain>/` and commits via the team git pipeline for auditability.
- `M1-MCP-04 — Skill applier (MCP-builder)` — Prepends matching skill text to ingestion prompts when a tenant's signature matches a known domain.

**QA**

- `M1-QA-01 — End-to-end smoke harness (QA)` — Ingest a small sample folder, run a query, see pages, hit the MCP endpoint, get tools back. Lives in `tests/e2e/`.
- `M1-QA-02 — Tenant-isolation property tests (QA)` — Forced cross-tenant calls must fail; per-tenant role enforcement must hold.

## In flight

- (none)

## Done

- `M0-01 — Recommend tech stack (Architect)` — `docs/architecture/stack.md`; decisions locked in `DECISIONS.md`.
- `M0-03 — Survey existing file-storage-to-wiki products (Researcher)` — `docs/research/landscape.md`.
- `M0-04 — Survey ontology-induction approaches (Researcher)` — `docs/research/ontology.md`.
- `M0-05 — Catalog prior MCP-server code worth reusing (Researcher)` — `docs/research/prior-art.md`.

## Icebox (not yet prioritized)

- Cross-customer pattern sharing protocol (M7)
- Mobile read-only viewer (M5)
- Billing & API key issuance UI
- Desktop "private mode" embedded Python ingestion (M3)
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6)

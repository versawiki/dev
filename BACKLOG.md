# Backlog

Prioritized top-to-bottom within each section. The Orchestrator pulls from "Ready" when spawning specialists. Items become "In flight" when a specialist is working on them, "Done" when merged.

Each ticket: `ID — title (role) — one-line description`. Heavier specs go in `docs/tickets/<id>.md`.

## Ready (M1 — Wave 3 candidates, all parallel-safe)

Dependency order, top-to-bottom. The next wave is BE-02 + ING-01 + MCP-01a, all of which are independent.

**Backend / API**

- `M1-BE-02 — API-key auth middleware (Backend)` — Issue, hash (argon2), validate, revoke, Redis-cached lookup. Per-tenant scoping. **Drop into the `api_key_required` dependency seam BE-01 already left.** Rename `StubApiKey` → `ApiKey`.
- `M1-BE-03 — Tenant schema provisioner (Backend)` — `CREATE SCHEMA vw_<slug>`; Alembic per-schema migration runner. Per-tenant Postgres role.
- `M1-BE-04 — Query API routes (Backend)` — `POST /v1/tenants/{tid}/query`, `GET /pages/{pid}`, `GET /ontology`. Mostly stubs at first.
- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)` — `search`, `read_page`, `read_chunk`, `list_ontology` tools. Streamable transport. Lives under `services/api/src/versawiki_api/mcp/` (placeholder already in place).

**Ingestion**

- `M1-ING-01 — Connector interface + local-folder connector (Ingestion)` — `Connector` interface (`list()`, `fetch(uri) -> bytes`, `watch() -> Iterator[ChangeEvent]`). Local-folder is the only impl in M1. Also: lift `parsers/base_parser.py`, `parsers/email_parser.py`, `parsers/excel_parser.py` from prior repo (per M0-06 audit) into `services/ingestion/parsers/`, swapping `project_id` for `tenant_id` + `source_id`.
- `M1-ING-02 — Chunker + embedder pipeline (Ingestion) — FULLY NET-NEW` — Per M0-06 surprise: the prior repo's embedding column is unused and `sentence-transformers` is commented out; search is pure `ILIKE`. We build the chunker + embedder + pgvector write path from scratch. RQ worker, idempotent on content hash. `EmbeddingProvider` abstraction; OpenAI `text-embedding-3-large@1024` as the M1 provider.
- `M1-ING-03 — Document classifier (Ingestion)` — LLM-based (Claude primary), with confidence + uncertainty signal piped to the meta-MCP for skill-write decisions. Adapt the prior repo's `document_types.yaml` taxonomy as cold-start seed (`services/ingestion/seeds/aec_starter_taxonomy.yaml`).
- `M1-ING-04 — Ontology inducer (Ingestion)` — BERTopic clustering + LLM-proposed taxonomy + Leiden community detection. Bootstraps from the AEC starter taxonomy.
- `M1-ING-05 — Wiki page builder (Ingestion)` — Stale-on-event materialisation; one page per ontology node + per cluster.
- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)` — Tracks query patterns; queues re-cluster/re-page jobs when distributions shift.

**Meta-MCP**

- `M1-MCP-01a — Privacy static checkers (MCP-builder)` — Implement the 5-stage pipeline specified in `docs/architecture/domain-observation-v1.md` §5: schema-validate → forbidden-field scan → PII/NER (spaCy + regex) → numeric-pattern → quote/near-quote (trigram overlap, query stays inside tenant) → opt-out gate. First hard failure short-circuits. Failed checks write `payload_hash + reason_code` to tenant-local audit log only.
- `M1-MCP-02 — Signature collector (MCP-builder)` — Subscribes to ingestion events, computes anonymized structural signatures per the 8 payload variants in domain-observation-v1.md, writes to the meta-tenant store.
- `M1-MCP-03 — Skill writer (MCP-builder)` — Threshold-triggered LLM job that writes domain-pattern skill markdowns to `services/meta-mcp/skills/<domain>/`, runs MCP-01a checkers on the generated text, and commits via the team git pipeline for auditability.
- `M1-MCP-04 — Skill applier (MCP-builder)` — Prepends matching skill text to ingestion prompts when a tenant's signature matches a known domain.
- `M1-MCP-05 — Per-tenant opt-out (MCP-builder)` — Tenant-level flag to disable even principle-sharing. Honored by signature collector and skill applier.

**QA**

- `M1-QA-01 — End-to-end smoke harness (QA)` — Ingest a small sample folder, run a query, see pages, hit the MCP endpoint, get tools back. Lives in `tests/e2e/`.
- `M1-QA-02 — Tenant-isolation property tests (QA)` — Forced cross-tenant calls must fail; per-tenant role enforcement must hold.
- `M1-QA-03 — Privacy-boundary property tests (QA)` — Generate synthetic `DomainObservation` payloads containing customer-specific names/figures/quotes; assert the static checkers reject every one. Generate "principle-only" payloads and assert they pass.

## In flight

- (none — Wave 2 just landed)

## Done

- `M1-BE-01 — FastAPI skeleton (Backend)` — `services/api/` with health + admin/tenants stubs, OpenAPI export, 8/8 tests passing. Locked patterns: error envelope, structlog-on-stderr, settings_dep, auth dep seam (`api_key_required → StubApiKey`).
- `M1-MCP-01 — DomainObservation event schema (Architect)` — `docs/architecture/domain-observation-v1.md` (561 lines). 8 payload variants, discriminated union, no free-form strings, numerics-as-buckets.
- `M0-06 — Audit prior MCP-server repo (Researcher)` — `docs/research/prior-art.md` updated with file-by-file table (3 REUSE / 11 ADAPT / 13 REPLACE). Surprise: prior is vector-RAG in name only.
- `M0-01 — Recommend tech stack (Architect)` — `docs/architecture/stack.md`; decisions locked in `DECISIONS.md`.
- `M0-02 — Draft v1 system design (Architect)` — `docs/architecture/v1.md`.
- `M0-03 — Survey existing file-storage-to-wiki products (Researcher)` — `docs/research/landscape.md`.
- `M0-04 — Survey ontology-induction approaches (Researcher)` — `docs/research/ontology.md`.
- `M0-05 — Catalog prior MCP-server code worth reusing (Researcher)` — `docs/research/prior-art.md` (live-probes pass; superseded by M0-06's real audit).

## Icebox (not yet prioritized)

- Cross-customer pattern sharing protocol (M7)
- Mobile read-only viewer (M5)
- Billing & API key issuance UI
- Desktop "private mode" embedded Python ingestion (M3)
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6)

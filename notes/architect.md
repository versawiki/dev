_Architect's working notes. Newest at top. Append when you wrap a session._

---

## 2026-05-22 — M1-MCP-01 DomainObservation event schema

**Wrote:** `docs/architecture/domain-observation-v1.md` — the wire contract for the tenant->meta-MCP boundary.

**Key design calls I made (all reversible inside v1.x):**

1. **`tenant_anon_id` = UUIDv4 issued at tenant provisioning.** Stored in `vw_<slug>.tenants.anon_id`; mapping is one-way at the meta boundary by construction. Rejected HMAC-with-rotating-key because rotation breaks the longitudinal correlation that is the meta layer's whole reason to exist. Tenant deletion (`DROP SCHEMA vw_acme CASCADE`) destroys the only mapping — that's the correct end-state.

2. **Eight payload variants in v1:** `OntologyShape`, `NamingConvention`, `DocumentTypeDistribution`, `RelationshipSchema`, `ProcedurePattern`, `QueryPatternShape`, `ClassifierUncertainty`, `IngestionPipelineMetrics`. Each one is a frozen Pydantic v2 model with `extra="forbid"`. Discriminated union on `kind`.

3. **Numbers cross only as buckets, ratios in [0,1], or low-resolution quantiles.** No raw counts ever. Static checker enforces this at emit time.

4. **All free-form strings are forbidden by construction.** Anywhere a "label" or "title" or "topic" would naturally go, the schema accepts only a `Literal[...]` from a fixed vocabulary, or a regex-constrained template like `<phase>-<discipline>-<sequence>` with role tokens drawn from another fixed vocabulary. There is no `str` field anywhere in any payload that accepts arbitrary user text.

5. **Static checker pipeline order:** schema validate -> forbidden-field-name scan -> PII/NER (spaCy + regex) -> numeric-pattern -> quote/near-quote (trigram overlap against tenant's own corpus, query stays inside tenant) -> opt-out gate. First hard failure short-circuits. Specified specifically enough that `M1-MCP-01a` implementor can wire it directly.

6. **Failed checks write payload_hash + reason_code to tenant-local audit_log only.** The offending payload is NOT logged anywhere, even tenant-side, to avoid the audit log becoming a back-door content store.

7. **Versioning is SemVer.** MINOR bumps allowed for new payload variants + new Literal members (collector treats unknown enums as `"other"`). MAJOR bumps require a translator on the meta side that reads from audit logs.

**Open questions surfaced for Josh (in section 8 of the doc):**

1. UUID-at-provisioning vs. HMAC-with-rotating-key for `tenant_anon_id`. **Recommend UUID.**
2. Controlled vocabulary location — baked into schema vs. external `vocabulary.yaml`. **Recommend baked-in for v1.**
3. Numeric buckets vs. differential privacy on raw counts. **Recommend buckets.**
4. Keep `tenant_anon_id` on envelope at all? **Recommend keep** — correlation across runs is the trigger condition for `M1-MCP-03` skill-write.
5. Audit-log retention policy. **Recommend life-of-tenant + admin-endpoint delete.**

**Downstream tickets now unblocked:** `M1-MCP-01a` (static checkers — sketch is concrete enough), `M1-MCP-02` (signature collector), `M1-MCP-03` (skill writer), `M1-MCP-04` (skill applier), `M1-MCP-05` (opt-out), `M1-QA-03` (privacy property tests).

**What I deliberately did NOT do this session:**

- No executable code outside the doc. Code snippets are illustrative; `M1-MCP-01a` / `M1-MCP-02` own implementation.
- No git operations (per session ground rules).
- Did not touch `BACKLOG.md` or `STATUS.md` (Orchestrator's job).

---

## 2026-05-22 — M0-01 + M0-02 first pass

**Wrote:**

- `docs/architecture/stack.md` — full v0.1 stack recommendation
- `docs/architecture/v1.md` — service decomp, data model, auth, MCP shape, meta-MCP self-write loop

**Headline picks (proposed for `DECISIONS.md`):**

1. **Backend = Python 3.12 + FastAPI 0.115.** The ML / agent ecosystem lives here and the existing `project-docs-*` MCPs the Researcher is cataloging in M0-05 are Python. If the Researcher comes back saying the prior code is large and reusable, this is doubly right. If they come back saying the prior code is small or unreusable, Python is still right on ecosystem grounds.
2. **Postgres 16 + pgvector 0.8 in the same DB.** One backup story, hybrid queries are trivial, scales further than people expect.
3. **Tenant isolation = schema-per-tenant on shared Postgres, enterprise tenants escalate to dedicated DB.** Belt-and-braces with per-tenant Postgres roles. RLS-only rejected — blast radius too big.
4. **MCP transport = MCP-over-HTTP (streamable).** Single endpoint, tenant resolved by API key. Per-tenant *tool surfaces* tuned by the meta-MCP.
5. **Meta-MCP boundary: aggregated structural signatures only; raw text never crosses; opt-out available.** Skills written as markdown to `services/meta-mcp/skills/` and committed to git for auditability.
6. **Clients: Next.js 15 web, Tauri 2 desktop, Expo SDK 52 mobile.** Shared TS types across all three.
7. **Embeddings: bge-m3 self-hosted default, OpenAI / Voyage fallback for enterprise tenants.**
8. **Hosting: Fly.io + Neon + Cloudflare R2.**

**Backlog tickets I'd propose for the Orchestrator to add to M1 (Backend / Ingestion / MCP-builder):**

- M1-BE-01: Stand up FastAPI skeleton with `/healthz`, `/v1/admin/tenants`, OpenAPI export.
- M1-BE-02: Implement API-key auth middleware (issue, hash, validate, revoke, Redis-cached lookup).
- M1-BE-03: Implement tenant schema provisioner (`CREATE SCHEMA vw_<slug>`; Alembic per-schema migration runner).
- M1-BE-04: Implement query API routes (`/query`, `/pages`, `/ontology`).
- M1-BE-05: Implement MCP-over-HTTP endpoint with `search`, `read_page`, `read_chunk`, `list_ontology` tools.
- M1-ING-01: `Connector` interface + local-folder connector.
- M1-ING-02: Chunker + embedder pipeline (RQ worker, idempotent on content hash).
- M1-ING-03: Classifier (LLM-based, with confidence + uncertainty signal).
- M1-ING-04: Ontology inducer (cluster + label + place in tree).
- M1-ING-05: Wiki page builder job (stale-on-event).
- M1-ING-06: Query-driven re-indexing scheduler.
- M1-MCP-01: Meta-MCP signature collector (ingests `DomainObservation` events).
- M1-MCP-02: Skill writer (LLM job; commits markdown to `services/meta-mcp/skills/`).
- M1-MCP-03: Skill applier (prepends skill text to ingestion prompts when signature matches).
- M1-QA-01: End-to-end smoke: ingest a sample folder, query it, see pages.

**Questions for Josh** (day-or-two rework stakes — flagged per the escalation rule):

1. **Meta-MCP data boundary — strict vs. loose.** My draft says "aggregated structural signatures only; no raw text ever leaves the tenant boundary." But ontology *labels* themselves (e.g., the string `"Battery storage RFIs"`) are arguably tenant content. Strict promise = labels stay tenant-side, meta-MCP sees only structural shapes. Loose promise = labels cross, cross-customer learning is much better. **Recommend: strict for v1, loosen with explicit opt-in once we have enterprise sales conversations.** Confirm?
2. **Schema-per-tenant as the default.** I'm choosing this over both RLS-only (too risky) and DB-per-tenant (too expensive at the bottom of the pricing tier). Enterprise tenants get dedicated DBs. Flipping this default later means a real migration. **Recommend: lock in schema-per-tenant.** Confirm?
3. **MCP transport: HTTP streamable.** Switching transports after clients exist is painful. SSE is simpler, WebSocket is more capable, HTTP streamable is the current MCP standard direction. **Recommend: HTTP streamable.** Confirm?
4. **Self-hosted embeddings (bge-m3) by default.** This means we own a GPU or a Modal/Replicate inference endpoint from day one. Alternative: start with OpenAI embeddings, self-host later. **Recommend: start hosted (OpenAI text-embedding-3-large) to avoid owning GPU ops in M1, swap to bge-m3 self-hosted before first enterprise tenant.** This is a softer call — happy to flip if Josh wants cost predictability from day one.
5. **Embedding dimension lock-in.** Whatever model we pick first, the `chunks.embedding vector(N)` column commits us to dimension N. If we start with text-embedding-3-large (3072) and switch to bge-m3 (1024), we re-embed everything. **Recommend: pick 1024 from day one (bge-m3 native, text-embedding-3-large can be Matryoshka-truncated to 1024 with mild quality loss).**

**Reconciliation note with Researcher (M0-05):** If the prior `project-docs-*` code is meaningfully reusable, we should adopt its chunker / embedder shape rather than write new ones. I've deliberately *not* over-specified those internals so we can absorb whatever the Researcher finds.

**What I'm leaving for later sessions:**

- API contract OpenAPI YAML (after Orchestrator confirms the picks above).
- Sequence diagrams for the ingestion run, the meta-MCP write loop, and the query-driven re-indexing trigger.
- The wire-format spec for `DomainObservation` (the anonymized event that crosses the tenant->meta boundary). This is the single highest-leverage contract in the system and deserves its own design doc.

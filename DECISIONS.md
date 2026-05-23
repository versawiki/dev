# Decision log

Append-only. Newest at top. Each entry: date, decision, rationale, made-by, reversibility cost.

The Orchestrator records decisions taken without escalating to Josh (per the day-or-two-rework rule). Josh's explicit decisions are recorded here too.

---

## 2026-05-22 — DomainObservation event schema design calls (accepted as locked)

The Architect's `docs/architecture/domain-observation-v1.md` surfaced 5 design questions. All five were within day-or-two-rework or reversible-cheaply, so Orchestrator accepted the Architect's recommendations rather than escalate.

**Decisions:**

1. **`tenant_anon_id` = UUIDv4 issued at tenant provisioning.** Stored in the tenant's own schema (`vw_<slug>.tenants.anon_id`). The only mapping from `anon_id` back to the customer-facing tenant identity lives inside the tenant's own database; tenant deletion destroys it. Rejected HMAC-with-rotating-key because rotation breaks the longitudinal correlation the meta-MCP needs for skill-write thresholds.
2. **Controlled vocabularies are baked into the Pydantic schema (Literal members) for v1.** Reject external `vocabulary.yaml`. Trading off vocabulary evolution velocity for type safety and review-via-diff. Re-evaluate if vocabularies grow beyond ~50 members per dimension.
3. **Numerics cross only as buckets, ratios in [0,1], or low-resolution quantiles.** No raw counts ever. Static checker enforces. Differential-privacy on raw counts considered and rejected for v1 (the per-query privacy budget is hard to allocate sensibly when the meta-MCP queries cross many tenants).
4. **`tenant_anon_id` stays on the envelope.** Correlation across observations from the same tenant is the trigger condition for `M1-MCP-03` skill-write; dropping it would make the meta-MCP signal-blind.
5. **Audit-log retention = life-of-tenant + admin-endpoint delete.** Stored only in the tenant's own schema. Failed-check entries record `payload_hash + reason_code` only — never the offending payload itself.

**Rationale:** Architect's recommendations were each grounded in versawiki's specific needs and each had a clear rollback path. Escalation cost (waking up Josh five times) exceeded the upside of his weighing in.

**Made by:** Orchestrator.

**Reversibility:** Each call is reversible inside v1.x of the DomainObservation schema (SemVer MINOR bump for additions; MAJOR for breaking changes). v2 would re-issue tenant_anon_ids and re-key historical observations via a translator.

---

## 2026-05-22 — Vector retrieval is genuinely net-new (M0-06 surprise)

**Decision:** Versawiki's chunker + embedder + vector retrieval (`M1-ING-02`, `M1-BE-04/05`) cannot reuse the prior repo's embedding path. The prior code has the schema column (`document_embeddings.embedding BYTEA`) but never writes to it; `sentence-transformers` is commented out in `requirements.txt`; search is pure `ILIKE`. We build embedding + vector search from scratch.

**Rationale:** M0-06 Researcher audit corrected M0-05's live-probe inference, which over-credited the prior code on this. The prior MCPs are vector-RAG in name only. ~30% of the assumed reuse evaporated.

**Made by:** Orchestrator (recording a Researcher finding as a planning fact, not a new design choice).

**Reversibility:** N/A — this is an observation about prior code, not a design call.

**Impact on backlog:** `M1-ING-02` is now flagged as "fully net-new — no prior code to lift." Estimate for the ticket increases. The "ADAPT" bucket of file lifts (parsers, registry, drive_connector, ingest, context_builder) is still valid.

---

# Decision log

Append-only. Newest at top. Each entry: date, decision, rationale, made-by, reversibility cost.

The Orchestrator records decisions taken without escalating to Josh (per the day-or-two-rework rule). Josh's explicit decisions are recorded here too.

---

## 2026-05-22 — Meta-MCP cross-tenant boundary = content-vs-pattern split

**Decision:** The meta-MCP cross-tenant boundary is not a strict/loose binary. It is a taxonomy:

- **MUST NOT cross** (treated as customer property): customer-specific names, figures, files, file names, file content excerpts, quotes (verbatim or near-verbatim). Plagiarism risk + privacy.
- **MAY cross** (treated as learned, generalizable knowledge): naming conventions, syntax patterns, organizational structures, data relationships, procedures, and other generally applicable properties of a data set or learned relationships within data.

Customers may opt out of even principle-sharing.

**Rationale:** Josh's call. Positioning-load-bearing: the customer pitch becomes "your *content* never leaves your tenant; only the *shapes you taught us* improve the product for everyone." Harder to engineer than strict-signatures-only — requires PII/NER redaction + quote detection + numeric-pattern detection as static checkers before any `DomainObservation` event leaves the tenant boundary and before any meta-MCP-authored skill markdown is committed. Preserves meaningful cross-customer learning value.

**Made by:** Josh.

**Reversibility:** Tightening later (removing things from the "may cross" list) = trivial. Loosening later (adding things) = potentially a credibility breach if customers were promised the stricter version. Bias toward stricter when ambiguous.

**Impact on backlog:** Ticket `M1-MCP-01` (DomainObservation event schema) is unblocked and must explicitly classify each field as principle-vs-content. Static-checker work (PII/NER + numeric pattern + quote detection) becomes a sibling ticket `M1-MCP-01a`.

---

## 2026-05-22 — Tech stack locked in (M0-01)

**Decision:** Python 3.12 + FastAPI 0.115 backend. Postgres 16 + pgvector 0.8 (same DB) with HNSW indexes. Next.js 15 (App Router) web. Tauri 2 desktop. Expo SDK 52 mobile. Redis 7 + RQ workers. Anthropic primary / OpenAI secondary for LLM access, behind an `LLMProvider` interface. Fly.io + Neon + Cloudflare R2 for hosting.

**Rationale:** Architect's recommendation in `docs/architecture/stack.md`, confirmed by Researcher's prior-art audit in `docs/research/prior-art.md` — the four `project-docs-*` MCPs are Python and ~70% reusable. Picking Python now eliminates a port. Both specialists corroborated on Postgres+pgvector. Next/Tauri/Expo share TypeScript types across all three clients.

**Made by:** Orchestrator (well-supported by both specialists; no contradictions; not a day-or-two-rework call once both pointed the same direction).

**Reversibility:** Backend language change = full rewrite (high cost). Other layers swap cheaper.

---

## 2026-05-22 — Tenant isolation = schema-per-tenant, with dedicated DB for enterprise

**Decision:** Each tenant gets its own Postgres schema (`vw_<tenant_slug>`) with a per-tenant Postgres role. Cross-schema queries are not used. Enterprise tenants escalate to a dedicated Neon database.

**Rationale:** Architect's call. Row-level-security-only was rejected because a single missed `WHERE tenant_id = $1` has catastrophic blast radius for a private-wiki product. Database-per-tenant is too expensive at the lower pricing tiers. Schema-per-tenant gives belt-and-braces isolation (role-bound) with shared connection pools and one logical migration story (Alembic per schema).

**Made by:** Orchestrator (accepting Architect's recommendation; reasoning was sound and the alternative is worse).

**Reversibility:** Migrating from schema-per-tenant to DB-per-tenant later = a real migration; the reverse direction is harder. Not flippable casually.

---

## 2026-05-22 — MCP transport = MCP-over-HTTP streamable

**Decision:** The per-tenant MCP endpoint uses the MCP-over-HTTP streamable transport. Single ingress URL; tenant resolved by the API key in the `Authorization` header.

**Rationale:** Architect's call. HTTP streamable is the standard direction the MCP spec is heading. SSE is a fallback. WebSocket would work but loads the client side with more complexity than we need.

**Made by:** Orchestrator.

**Reversibility:** Switching transports after clients ship is painful. We're committing early on purpose.

---

## 2026-05-22 — Embedding plumbing: dimension 1024 locked, model starts hosted, swaps to self-hosted before M3

**Decision:** `chunks.embedding vector(1024)` is locked from day one. M1 uses OpenAI `text-embedding-3-large` truncated to 1024 dims (Matryoshka-style) via an `EmbeddingProvider` interface. Before M3 (desktop ingestion, where on-device or low-cost matters), swap to a self-hostable open-weights model — `bge-m3` (Architect's lean) and `nomic-embed-text-v2` (Researcher's lean) both fit 1024 natively. Final model choice locked by an M1-tail spike.

**Rationale:** Both specialists flagged embedding-model selection as day-or-two-rework. The honest answer: dimension is the load-bearing commitment; specific model is swappable behind an interface as long as dimension matches. Starting hosted avoids GPU ops in M1 while we still have no customers. The provider interface is a small cost; the freedom it buys is large.

**Made by:** Orchestrator (synthesizing both specialists' positions; neither was wrong, but neither saw the dim-vs-model split clearly).

**Reversibility:** Swap models = re-embed corpus (cheap on M1 fixtures; would be expensive at scale, but we're far from scale). Change dimension = schema migration + re-embed. We're locking dimension to lock the schema, leaving model fluid.

---

## 2026-05-22 — Ontology pipeline: build our own (Researcher's M0-04 recommendation)

**Decision:** M1 ontology pipeline is `BERTopic-grounded clusters -> LLM-proposed type taxonomy -> entity graph + Leiden community detection -> pre-materialised wiki pages -> query feedback loop`, all in Postgres + pgvector. We do NOT adopt Microsoft GraphRAG wholesale.

**Rationale:** Researcher's M0-04 + F-02 reasoning: we'll need our own prompts for the meta-MCP anyway, so adopting GraphRAG's opinionated prompt set buys little and costs flexibility. Reimplementing the Leiden + community-detection stage on top of pgvector is a few-day job, not a few-week one.

**Made by:** Orchestrator (Researcher recommended; Architect didn't dispute).

**Reversibility:** Moderate. Swap-in of GraphRAG later is possible but the integration points would shift.

---

## 2026-05-22 — Smaller calls bundled (no graph DB / no fine-tuning / AEC starter taxonomy in M1)

**Decisions:**

- **No dedicated graph DB in M1.** Polymorphic relation table in Postgres covers it.
- **No fine-tuning in M1.** Prompt + retrieval is competitive at this corpus size (MDPI 2025 comparative study cited by Researcher); we save fine-tuning as a meta-MCP capability where cross-tenant data exists.
- **Starter taxonomy = AEC lifted from the `project-docs-*` MCPs.** LLM induction replaces it on the first ingestion of any tenant whose corpus isn't AEC.
- **pgvector index = HNSW**, not IVFFlat.

**Rationale:** Researcher's "smaller calls" section; all reversible cheaply.

**Made by:** Orchestrator.

**Reversibility:** All cheap.

---

## 2026-05-22 — Orchestration model is mission-driven, not scheduled

**Decision:** Versawiki's agent team is coordinated by Claude acting as Orchestrator at the start of each session, spawning specialists via the Task tool. No scheduled-task cron.

**Rationale:** Josh prefers the team to act on next-best need rather than clock cadence. Specialists run in parallel where independent; serial when blocked. Orchestrator makes day-or-two-rework-stakes calls without asking.

**Made by:** Josh.

**Reversibility:** Trivial — we can layer scheduled tasks on top later if needed.

---

## 2026-05-22 — First-built connector is local folder

**Decision:** M1 targets local-folder ingestion only. Google Drive, OneDrive/SharePoint, Dropbox/Box, iCloud follow in that order.

**Rationale:** Local first eliminates OAuth, scopes, and rate limits so we can validate the hard parts (classification, ontology induction, query-driven re-indexing) on a fast loop. The connector layer becomes a thin adapter once the core works.

**Made by:** Josh.

**Reversibility:** Cheap — the ingestion interface should be connector-agnostic from day one anyway.

---

## 2026-05-22 — Code lives at github.com/versawiki/dev

**Decision:** The team commits to `github.com/versawiki/dev`, branch `main`. Git is split: git-dir at `/tmp/vw_git`, work-tree at the workspace mount (Cowork mount blocks normal `.git` operations).

**Rationale:** Josh wants real version history and the ability to review work from mobile. Empty repo confirmed on GitHub. Push credential pending — for the initial bundle, Josh pushes from his laptop; ongoing pushes via a fine-grained PAT that Josh provides in a later session.

**Made by:** Josh.

**Reversibility:** Trivial.

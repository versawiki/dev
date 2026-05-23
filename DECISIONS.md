# Decision log

Append-only. Newest at top. Each entry: date, decision, rationale, made-by, reversibility cost.

The Orchestrator records decisions taken without escalating to Josh (per the day-or-two-rework rule). Josh's explicit decisions are recorded here too.

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

**Rationale:** Josh wants real version history and the ability to review work from mobile. Empty repo confirmed on GitHub. Push credential pending.

**Made by:** Josh.

**Reversibility:** Trivial.

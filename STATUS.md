# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Current milestone

**M1 — Local-folder ingestion (headless).** 368 tests passing across three services. The full ingestion → classification → meta-MCP → skill-write learning loop now exists in code.

## Last session summary (2026-05-22 → 2026-05-23, Wave 5)

**Wave 5 (3 parallel specialists):**

- **Backend (M1-BE-04 — 94/94, +17)** — Query API routes: `POST /v1/tenants/{tid}/query`, `GET /pages/{pid}`, `GET /ontology`. Tenant-scope enforcement (`tenant_scope_mismatch` 403) checked BEFORE existence so 404-vs-403 cannot leak tenant ids. `EmbeddingProviderDep` wires StubEmbeddingProvider in test/dev, OpenAI in prod. Tenant resolver pinned by a dedicated test.
- **Ingestion (M1-ING-03 — 133/133, +43)** — LLM document classifier. `ClassifierResult` with `predicted_type`, `confidence`, top-3 `alternatives`, `uncertainty_reason` (LOW_CONFIDENCE / TIE_BETWEEN_TYPES / NOVEL_PATTERN), interpretable `signals` dict feeding meta-MCP. Disagreement logic between LLM and heuristic match score drops confidence and tags reason. Stub provider deterministic; Anthropic/OpenAI providers mocked in tests.
- **Meta-MCP (M1-MCP-03 — 141/143, +35)** — Skill writer. SignatureAggregator queries meta-store and selects (domain, kind) groups crossing thresholds (`min_distinct_tenants=3`, `min_observations=25`, `confidence_floor=0.65`). LLM writes markdown skill draft. **Draft must pass a text-shaped checker (built on top of MCP-01a primitives) BEFORE the file is written.** Rejected drafts go to a global audit log (hash + reason only). Versioning increments on same (domain, kind, title). Git commit happens via subprocess (mocked in tests).

**Total: 368 tests passing** (api 94 + ingestion 133 + meta-mcp 141).

**The learning loop is now closed in code:** parse → chunk → embed → classify → emit ClassifierUncertainty / DocumentTypeDistribution / etc. signatures → SignatureCollector gates through MCP-01a → FileMetaStore persists → SignatureAggregator detects cross-tenant patterns → SkillWriter drafts markdown → text-checker gates → write to `services/meta-mcp/skills/<domain>/...` → git commit. Every byte that crosses the tenant boundary goes through a checker.

## In flight

- (none — Wave 5 just landed)

## Blockers awaiting Josh

- (none)

## Next intended action (Wave 6 candidates)

1. **Backend** — `M1-BE-05` MCP-over-HTTP endpoint. `search`, `read_page`, `read_chunk`, `list_ontology` tools. Reuses BE-04's `get_tenant_session` and `EmbeddingProviderDep` verbatim.
2. **Ingestion** — `M1-ING-04` Ontology inducer. BERTopic + LLM-proposed taxonomy + Leiden community detection over the embedded chunks.
3. **MCP-builder** — `M1-MCP-04` Skill applier. Prepends matching skill text to ingestion prompts when a tenant's signature matches a known domain.

## Quick links

- `README.md`, `ROADMAP.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, `ARCHITECTURE-LAYOUT.md`
- `docs/architecture/{stack,v1,domain-observation-v1}.md`
- `docs/research/{landscape,ontology,prior-art}.md`
- `services/api/` — FastAPI + auth + Postgres provisioner + query routes (BE-01..04)
- `services/ingestion/` — connector + parsers + chunker/embedder + classifier (ING-01..03)
- `services/meta-mcp/` — privacy checkers + audit log + signature collector + meta-store + skill writer (MCP-01a, 02, 03)
- `notes/*` — per-role working logs

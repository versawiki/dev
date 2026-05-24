# Backlog

Prioritized top-to-bottom within each section.

## Ready (M1 — what's left)

**Ingestion**

- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)`.

**Customer Support (new)**

- `M1-CS-02 — Structured Anthropic tool-use (Support)` — Refactor to native tool-use loop.
- `M1-CS-03 — Wire admin API (Support)` — Connect agent actions to real BE-03 admin endpoints with a service token.
- `M1-CS-04 — SMTP outbound (Support)` — Postmark/SendGrid for sending replies.
- `M1-CS-05 — Notifier (Support)` — Slack/Telegram/email push when escalations land.
- `M1-CS-06 — Web chat widget (Support)` — Small React component for marketing site + app.
- `M1-CS-07 — Escalation review UI (Support)` — Tiny page for Josh to review/reply/close queued escalations.

**Operations (new — Josh-driven mostly)**

- `OPS-02 — Apple Developer + Google Play accounts` — Per `docs/operations/app-store-prep.md`.
- `OPS-03 — LLC + bank + EIN` — **Florida chosen.** File via Sunbiz.org ($125) + EIN from IRS (free) + Mercury bank account + registered agent. Skip Stripe Atlas (Delaware-only). See `docs/operations/llc-and-business.md` (Florida addendum).
- `OPS-04 — Claude Agent SDK orchestrator on the GCP VM` — Per `docs/operations/agent-sdk-spec.md`. ~3 working days when ready.
- `OPS-05 — Privacy policy + ToS + DPA drafts` — Termly/Iubenda templates, then lawyer review.
- `OPS-06 — Production infrastructure (Fly + Neon + R2 accounts)` — Just-in-time before M1 deploy.
- `OPS-07 — Stripe billing` — After LLC closes.

**QA**

- `M1-QA-03 — Privacy-boundary property tests`.

## Overnight safe list (cron picks from here)

`M1-QA-03`. (None of the new OPS or CS tickets — they touch external systems / need credentials.)

## In flight

- `OPS-04 — Claude Agent SDK orchestrator on the GCP VM` — Code shipped under `services/orchestrator/`. 39 tests passing. Dockerfile + compose snippet + step-by-step VM deploy guide at `docs/operations/orchestrator-deploy.md`. **Josh next**: paste-and-build on the VM (observe mode for 48h, then flip to act).

## Done

- `M1-QA-02 — Tenant-isolation property tests (QA / Ingestion)` — New `services/ingestion/tests/e2e/test_tenant_isolation_properties.py` (406 lines, 7 `@pytest.mark.asyncio` tests). Drives `InMemoryPageStore` with a seeded `random.Random` (SEED=20260524, +0..+4 per-test offsets) across N=20+ tenants per scenario, with intentional id/slug/ontology-node-id collisions across tenants. Tests: `test_property_get_never_crosses_tenants`, `test_property_get_by_slug_never_crosses_tenants` (collision-aware: result is `None` or a page whose `tenant_id` matches the queried tenant), `test_property_list_for_node_never_crosses_tenants`, `test_property_mark_stale_never_crosses_tenants` (skips collision pairs, asserts owner's copy stays non-stale), `test_property_same_id_across_tenants_isolated`, `test_property_same_slug_across_tenants_isolated`, `test_property_concurrent_cross_tenant_upserts_dont_leak` (gathered asyncio upserts across tenants). Cross-tenant probe counts ~380 per main test, well above the 100-probe floor. Self-contained: local `_page()` helper mirrors `test_page_store_inmemory.py`; no `hypothesis` dep (rolled inline). +7 tests in ingestion (238 → 245). Commit `20c556b` (overnight cron).
- `M1-QA-01 — End-to-end smoke harness (QA / Ingestion)` — `services/ingestion/tests/e2e/` (net-new package: `__init__.py`, `conftest.py`, `test_smoke_local_folder_to_pages.py`). Single-process, stub-LLM-driven smoke that exercises `LocalFolderConnector → process_document → OntologyInducer → PageBuildPipeline → InMemoryPageStore` end-to-end on a 7-file synthetic corpus (mixed `.txt`/`.eml`/`.xlsx`, RFI + meeting-minutes shapes, one tiny rollup file). 1 module-scoped `smoke_result` fixture runs the heavy pipeline once; 8 async tests cover: corpus processed, ontology tree built, ≥1 page produced, id+slug retrievability, four expected section headers in `body_markdown`, no self-loop in `related_page_ids`, cross-tenant `get` returns None, determinism over two runs (Metadata "Last updated" line stripped before compare). No new deps; no cross-service imports. Three implementation notes worth flagging for the M1-QA-01b follow-up: (i) `WikiPage` field is `body_markdown` not `body_md`; (ii) `classifier_results` is keyed by `document_content_hash` (not `source_uri`); (iii) slug uniqueness is not guaranteed by the store contract — two distinct nodes with the same inducer label can collide on slug, so the by-slug test asserts only that *some* page with the matching slug comes back. +8 tests in ingestion (230 → 238). Commit `23b767e` (overnight cron).
- `M1-MCP-05 — Per-tenant opt-out (MCP-builder / Backend)` — `opt_out_signature_sharing` Boolean column added to `vw_admin.tenants` (alembic `20260523_0002`); threaded through `TenantRecord` + `InMemoryTenantStore` + `PostgresTenantStore` with a `set_opt_out(tenant_id, opt_out_signature_sharing=...)` mutator; surfaced on `TenantOut`; new admin-scoped `PATCH /v1/admin/tenants/{tenant_id}/opt-out` route with structured 404 on unknown tenant and `extra='forbid'` request body. Meta-MCP consumer side (`TenantSignatureConfig.opt_out` honored in collector + applier) was already wired and is unchanged. +12 tests in api (129 → 141). Commit `e928f72` (overnight cron).
- `M1-MCP-01a-fix — Branching-factor real-stat band (MCP-builder)` — `services/meta-mcp/src/versawiki_meta_mcp/checkers/numeric.py`; new `ALLOWED_REAL_STAT_LEAVES` bucket holds `branching_factor_p50/p95` as non-negative floats < `STRUCTURAL_COUNT_MAX` (1000) instead of ratio-clamped at [0,1]. xfail on `test_branching_factor_above_one_should_pass` removed; `test_ratio_out_of_range_rejected` rewritten to bypass the schema (use `adherence_rate` direct-unit call) since every schema-level ratio is `Field(le=1.0)` and would short-circuit at stage 1. +2 new unit tests (real-stat passes, > MAX rejected). meta-mcp 166 → 169 passed. Commit `a1d6939` (overnight cron).
- `M1-ING-03c — Taxonomy (catch-all) annotation in classifier prompt (Ingestion)` — `services/ingestion/src/versawiki_ingestion/classification/prompts.py` gains a `catch_all_types` kwarg; both LLM providers pass `{taxonomy.default_type, taxonomy.unclassified_type}`. +5 tests in ingestion (225→230). Commit `087a59c` (landed independently of the overnight cron; the cron detected the duplicate at push time, abandoned its own `54ddb1b`, and updated bookkeeping — see `notes/orchestrator.md`).
- `M1-ING-03b — Classifier retry on LLM 429/5xx (Ingestion)` — `services/ingestion/src/versawiki_ingestion/classification/llm_provider.py`; shared `_post_with_retries` helper, 3 attempts, exponential backoff (1s → 2s → fail-to-degrade). +10 tests (215→225). Commit `227f5a2` (overnight cron).
- `M1-ING-05 — Wiki page builder (Ingestion)` — `services/ingestion/src/versawiki_ingestion/pages/`; 35 new tests (215 total) + 14 new in api (129 total). Stale-on-event materialisation. Pages route flipped from 404 to real lookup; MCP `read_page` now returns real data.
- `M1-CS-01 — Customer support agent v1 (Support)` — `services/support-agent/`; 62 tests; safe/forbidden actions; PII redaction; cross-tenant block. Load-bearing tests: `test_cross_tenant_lookup_refused_and_audited_not_escalated`, `test_conversation_log_never_contains_cc_number`.
- `M1-MCP-04 — Skill applier (MCP-builder)`.
- `M1-ING-04 — Ontology inducer (Ingestion)`.
- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)`.
- `M1-MCP-03 — Skill writer (MCP-builder)`.
- `M1-ING-03 — Document classifier (Ingestion)`.
- `M1-BE-04 — Query API routes (Backend)`.
- `M1-MCP-02 — Signature collector (MCP-builder)`.
- `M1-ING-02 — Chunker + embedder pipeline (Ingestion)`.
- `M1-BE-03 — Tenant schema provisioner (Backend)`.
- `M1-MCP-01a — Privacy static checkers (MCP-builder)`.
- `M1-ING-01 — Connector interface + local-folder connector (Ingestion)`.
- `M1-BE-02 — API-key auth middleware (Backend)`.
- `M1-BE-01 — FastAPI skeleton (Backend)`.
- `M1-MCP-01 — DomainObservation event schema (Architect)`.
- `OPS-01 — Cloudflare DNS migration` — Josh completed 2026-05-23; all 4 domains now on Cloudflare nameservers. Records + workers still to configure as services come online.
- `M0-01..06 — All M0 tickets done`.

## Icebox

- M1-BE-03b — PostgresTenantStore integration coverage.
- M1-BE-03c — Per-request `SET ROLE` / `search_path` dep.
- M1-BE-05b — Real chunks SQL in `tool_search` (needs pgvector activation).
- M1-MCP-04b — Real LLM matchers.
- Wire ING-04's OntologyInducer into a corpus-level orchestrator.
- Cross-customer pattern sharing protocol (M7).
- Mobile read-only viewer (M5).
- Billing & API key issuance UI.
- Desktop "private mode" embedded Python ingestion (M3).
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6).

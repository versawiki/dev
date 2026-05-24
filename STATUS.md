# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Last session summary

- **2026-05-24 overnight cron** — `20c556b` — M1-QA-02: tenant-isolation property tests (ingestion). New `services/ingestion/tests/e2e/test_tenant_isolation_properties.py` (406 lines, 7 `@pytest.mark.asyncio` tests) drives `InMemoryPageStore` with a seeded `random.Random` (SEED=20260524) across N=20+ tenants per scenario, with intentional id/slug/node-id collisions across tenants. Covers: `get`, `get_by_slug`, `list_for_node`, `mark_stale` never crossing tenants (several hundred cross-tenant probes per test), same-id and same-slug across tenants stay isolated, and `asyncio.gather`'d concurrent upserts across tenants don't leak. Self-contained file (local `_page()` helper mirrors `test_page_store_inmemory.py`). No new deps, no production code touched. ingestion 238 → 245 (+7). New file passes 7 in 0.04s; full ingestion suite 245 passed in 3.60s.
- **2026-05-23 overnight cron** — `23b767e` — M1-QA-01: end-to-end smoke harness (ingestion). New `services/ingestion/tests/e2e/` (conftest + 8 async tests) drives `LocalFolderConnector` → `process_document` → `OntologyInducer` → `PageBuildPipeline` → `InMemoryPageStore` end-to-end on a 7-file synthetic corpus using `StubLLMClassifier`/`StubEmbeddingProvider`/`StubPageWriter`. Covers: corpus processed, tree built, ≥1 page, id+slug retrievability, four section headers in `body_markdown`, no self-loop in `related_page_ids`, tenant isolation (cross-tenant `get` returns None), determinism over two runs (Metadata "Last updated" line stripped). No new deps, no cross-service imports. ingestion 230 → 238 (+8). Out-of-scope follow-up flagged: M1-QA-01b (over-the-wire FastAPI smoke that crosses ingestion → api).
- **2026-05-23 overnight cron** — `e928f72` — M1-MCP-05: per-tenant opt-out flag API + persistence. Adds `opt_out_signature_sharing` Boolean column to `vw_admin.tenants` (alembic `20260523_0002`), threads it through `TenantRecord` + both `TenantStore` impls (`InMemory` + `Postgres`) with a `set_opt_out` mutator, and exposes a new `PATCH /v1/admin/tenants/{tenant_id}/opt-out` admin route. The meta-MCP consumer side (`TenantSignatureConfig.opt_out` in collector + applier) is unchanged. +12 tests in api (129 → 141, 2 pre-existing integration skips unchanged).
- **2026-05-23 overnight cron** — `a1d6939` — M1-MCP-01a-fix: numeric checker accepts `branching_factor_p50/p95` as real-valued statistics (non-negative floats < STRUCTURAL_COUNT_MAX), no longer ratio-clamped at [0,1]. New `ALLOWED_REAL_STAT_LEAVES` bucket in `numeric.py`. xfail on `test_branching_factor_above_one_should_pass` removed; `test_ratio_out_of_range_rejected` rewritten to bypass schema; +2 new unit tests. meta-mcp: 166 → 169 passed, 1 skipped (unchanged), 0 xfailed.
- **2026-05-23 interactive** — OPS-04 v0 lands in `services/orchestrator/`: Claude Agent SDK wrapper, FastAPI control API, SQLite audit log with hash chain, spending caps (Sonnet default, $20/day), branch-only PR writer, SMTP escalation, Dockerfile + compose snippet, full VM deploy guide. 39 orchestrator tests passing. Mode defaults to **observe** — agent runs but PRs aren't opened for the first 48h soak. Next: Josh runs the deploy walkthrough on the VM.
- **2026-05-23 overnight cron** — *no new commit by cron* — Picked M1-ING-03c off the top of the safe list; specialist completed it cleanly (225→230 in ingestion, +5 tests, all green). At push time discovered `origin/main` had advanced to `087a59c` with a functionally identical M1-ING-03c commit landed independently. Cron abandoned its `54ddb1b`, reset to `origin/main`, and pushed this BACKLOG/STATUS/notes bookkeeping fix instead. See `notes/orchestrator.md` top entry.
- **2026-05-23 overnight cron** — `227f5a2` — M1-ING-03b: Classifier retry on LLM 429/5xx (Anthropic + OpenAI providers, shared `_post_with_retries` helper, exponential backoff matching the embedder pattern). +10 tests in ingestion (215 → 225). All 582 tests green.
- **2026-05-23 follow-up** — `087a59c` — M1-ING-03c: catch-all annotation in classifier prompt (Anthropic + OpenAI providers, +5 tests in ingestion, 225 → 230). Landed independently of the overnight cron; cron detected the duplicate and stopped cleanly.

## Current milestone

**M1 — Local-folder ingestion (headless).** End-to-end loop closed in code. **617 tests passing** across four services. An ingested folder produces queryable wiki pages all the way through the system.

## Per-service current state

- `services/api/` — **141 tests** (+12 from M1-MCP-05's opt-out PATCH route + persistence) — Full M1 backend (auth + provisioner + query routes + MCP-over-HTTP + real pages route + per-tenant opt-out admin surface).
- `services/ingestion/` — **245 tests** (+7 from M1-QA-02's tenant-isolation property tests on `InMemoryPageStore`) — Connector + parsers + chunker/embedder + classifier (with 429/5xx retry + catch-all annotation in prompt) + ontology inducer + wiki page builder.
- `services/meta-mcp/` — **169 tests** — Privacy checkers + audit log + signature collector + meta-store + skill writer + skill applier.
- `services/support-agent/` — **62 tests** — Autonomous CS: KB, safe/forbidden actions, PII redaction, cross-tenant block, intake adapters, escalation queue.

## The end-to-end loop in code

```
LocalFolderConnector → Parsers → Chunker → EmbeddingProvider →
  ClassifierResult → OntologyInducer (BERTopic/Leiden fallbacks active) →
    PageBuilder → InMemoryPageStore →
      GET /v1/tenants/{tid}/pages/{pid} returns real page →
      MCP read_page tool returns real page
```

Plus the meta-MCP loop running orthogonally: signatures emit through privacy checkers → FileMetaStore → SkillWriter drafts → text-checker gate → skills/<domain>/...md → SkillApplier prepends learned text on next ingestion.

## Credentials on disk (gitignored)

- `.vw-cron-token` — GitHub PAT (for push)
- `.vw-anthropic-key` — for the classifier, taxonomy proposer, page writer, skill writer, support agent
- `.vw-openai-key` — for the embedding provider

All three protected by the `.vw-*` patterns in `.gitignore`; verified with `git check-ignore -v` after each write. NONE of them ever land in a commit, and they are NOT saved to my long-term memory.

## Overnight cron status

Still live. Safe list shrunk by one more (M1-QA-02 now Done via `20c556b`). Remaining: `M1-QA-03`. Next fire's top pick: `M1-QA-03` (privacy-boundary property tests).

## Blockers awaiting Josh

- (none code-wise — every keys we have are in)
- Pending in your hands per the operations docs: Apple Developer signup, Florida LLC filing, OPS-04 (Claude Agent SDK on VM) decision

## Next interactive tickets (morning, in order of leverage)

1. **M1-QA-01 end-to-end smoke against a real corpus** — now possible with both keys + ING-05. Point it at the prior MCP repo's docs as a corpus and verify the whole pipeline produces pages.
2. **M1-CS-03/04 wire support agent to admin API + SMTP** — gets customer support actually functional.
3. **OPS-04 deploy** — paste the walkthrough at `docs/operations/orchestrator-deploy.md` into the VM CLI. ~30 min wall-clock.

## Quick links

- `README.md`, `ROADMAP.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, `ARCHITECTURE-LAYOUT.md`
- `docs/architecture/{stack,v1,domain-observation-v1}.md`
- `docs/research/{landscape,ontology,prior-art}.md`
- `docs/operations/*.md`
- `services/{api,ingestion,meta-mcp,support-agent}/`
- `notes/*` — per-role working logs

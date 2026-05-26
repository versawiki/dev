# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Last session summary

- **2026-05-26 interactive (Josh + Claude)** — OPS-04 disposition triage. Discovered the `versawiki-orchestrator` container had been running on the VM (`project-mcp-server`, `/home/joshuafausset/versawiki-orchestrator/`) in `act` mode for ~2 days and had self-paused on the `$20/day` spend cap. Audit log (68,404 rows, hash chain verified) showed the agent picked `M1-MCP-05` every ~5-min tick from 2026-05-23 16:52 to 19:50 UTC, didn't notice the Cowork cron had already merged it that morning, and opened 19 PRs (12 duplicate impl PRs for MCP-05 / QA-01-03 / MCP-01a-fix + 7 meta `[needs-review]` PRs flagging the clogged-queue state). Auto-merger refused all 19 (`too_many_lines` / `needs_review` / `no_checks` — safety guardrails worked as designed). Recovery actions: (a) `docker stop versawiki-orchestrator` (exit 0); (b) closed all 19 open PRs with explanatory comments via REST API, branches retained for forensics; (c) paused the Cowork `vw-overnight` scheduled task (was firing every 4h, had hit 12 consecutive no-ops since safe list exhausted on 2026-05-24); (d) moved OPS-04 from In flight → Done in BACKLOG, replaced the stale "Josh next: paste-and-build" entry. Both autonomous agents now off; next move is Josh's disposition call (act / observe / disable). **SMTP escalation gap**: the orchestrator hit `needs_review` dozens of times without sending any email — either SMTP was never configured at deploy time, or `escalation_sent` requires a different trigger; investigate before any resume.
- **2026-05-24 overnight cron** — `d906ce9` — M1-QA-03: privacy-boundary property tests (meta-mcp). New `services/meta-mcp/tests/e2e/test_privacy_boundary_properties.py` (781 lines, 8 property tests) hammers `CheckerPipeline` with N>=20 randomized cases per scenario (seeded `random.Random`, SEED=20260524). Invariants exercised: principle-only payloads always pass all 6 stages; PII spliced into `tenant_anon_id` rejected at `PII_NER` (email/phone/SSN; URL/IPv4 omitted per `pii.py` coverage); forbidden field names rejected at stage 2 (calls `scan_forbidden_field_names` directly since `extra='forbid'` schema short-circuits at stage 1 otherwise); `opt_out_flag=True` blocks at `OPT_OUT_GATE` while stages 1-5 still record `passed=True`; free strings >64 chars rejected at `QUOTE_NEAR_QUOTE` (`STRING_TOO_LONG`); `payload_hash` deterministic under replay and distinct across `tenant_anon_id`; stage ordering short-circuits at the first failure. Self-contained file (local `_build_envelope` helper). No production code touched, no new deps. meta-mcp: 171 -> 179 passed (1 pre-existing spaCy skip unchanged).
- **2026-05-24 overnight cron** — `20c556b` — M1-QA-02: tenant-isolation property tests (ingestion). New `services/ingestion/tests/e2e/test_tenant_isolation_properties.py` (406 lines, 7 `@pytest.mark.asyncio` tests) drives `InMemoryPageStore` with a seeded `random.Random` (SEED=20260524) across N=20+ tenants per scenario, with intentional id/slug/node-id collisions across tenants. Covers: `get`, `get_by_slug`, `list_for_node`, `mark_stale` never crossing tenants (several hundred cross-tenant probes per test), same-id and same-slug across tenants stay isolated, and `asyncio.gather`'d concurrent upserts across tenants don't leak. Self-contained file (local `_page()` helper mirrors `test_page_store_inmemory.py`). No new deps, no production code touched. ingestion 238 → 245 (+7). New file passes 7 in 0.04s; full ingestion suite 245 passed in 3.60s.
- **2026-05-23 overnight cron** — `23b767e` — M1-QA-01: end-to-end smoke harness (ingestion). New `services/ingestion/tests/e2e/` (conftest + 8 async tests) drives `LocalFolderConnector` → `process_document` → `OntologyInducer` → `PageBuildPipeline` → `InMemoryPageStore` end-to-end on a 7-file synthetic corpus using `StubLLMClassifier`/`StubEmbeddingProvider`/`StubPageWriter`. Covers: corpus processed, tree built, ≥1 page, id+slug retrievability, four section headers in `body_markdown`, no self-loop in `related_page_ids`, tenant isolation (cross-tenant `get` returns None), determinism over two runs (Metadata "Last updated" line stripped). No new deps, no cross-service imports. ingestion 230 → 238 (+8). Out-of-scope follow-up flagged: M1-QA-01b (over-the-wire FastAPI smoke that crosses ingestion → api).
- **2026-05-23 overnight cron** — `e928f72` — M1-MCP-05: per-tenant opt-out flag API + persistence. Adds `opt_out_signature_sharing` Boolean column to `vw_admin.tenants` (alembic `20260523_0002`), threads it through `TenantRecord` + both `TenantStore` impls (`InMemory` + `Postgres`) with a `set_opt_out` mutator, and exposes a new `PATCH /v1/admin/tenants/{tenant_id}/opt-out` admin route. The meta-MCP consumer side (`TenantSignatureConfig.opt_out` in collector + applier) is unchanged. +12 tests in api (129 → 141, 2 pre-existing integration skips unchanged).
- **2026-05-23 overnight cron** — `a1d6939` — M1-MCP-01a-fix: numeric checker accepts `branching_factor_p50/p95` as real-valued statistics (non-negative floats < STRUCTURAL_COUNT_MAX), no longer ratio-clamped at [0,1]. New `ALLOWED_REAL_STAT_LEAVES` bucket in `numeric.py`. xfail on `test_branching_factor_above_one_should_pass` removed; `test_ratio_out_of_range_rejected` rewritten to bypass schema; +2 new unit tests. meta-mcp: 166 → 169 passed, 1 skipped (unchanged), 0 xfailed.
- **2026-05-23 interactive** — OPS-04 v0 lands in `services/orchestrator/`: Claude Agent SDK wrapper, FastAPI control API, SQLite audit log with hash chain, spending caps (Sonnet default, $20/day), branch-only PR writer, SMTP escalation, Dockerfile + compose snippet, full VM deploy guide. 39 orchestrator tests passing. Mode defaults to **observe** — agent runs but PRs aren't opened for the first 48h soak. (Subsequently deployed and run; see 2026-05-26 entry for the outcome.)
- **2026-05-23 overnight cron** — *no new commit by cron* — Picked M1-ING-03c off the top of the safe list; specialist completed it cleanly (225→230 in ingestion, +5 tests, all green). At push time discovered `origin/main` had advanced to `087a59c` with a functionally identical M1-ING-03c commit landed independently. Cron abandoned its `54ddb1b`, reset to `origin/main`, and pushed this BACKLOG/STATUS/notes bookkeeping fix instead. See `notes/orchestrator.md` top entry.
- **2026-05-23 overnight cron** — `227f5a2` — M1-ING-03b: Classifier retry on LLM 429/5xx (Anthropic + OpenAI providers, shared `_post_with_retries` helper, exponential backoff matching the embedder pattern). +10 tests in ingestion (215 → 225). All 582 tests green.
- **2026-05-23 follow-up** — `087a59c` — M1-ING-03c: catch-all annotation in classifier prompt (Anthropic + OpenAI providers, +5 tests in ingestion, 225 → 230). Landed independently of the overnight cron; cron detected the duplicate and stopped cleanly.

## Current milestone

**M1 — Local-folder ingestion (headless).** End-to-end loop closed in code. **627 tests passing** across four services. An ingested folder produces queryable wiki pages all the way through the system.

## Per-service current state

- `services/api/` — **141 tests** (+12 from M1-MCP-05's opt-out PATCH route + persistence) — Full M1 backend (auth + provisioner + query routes + MCP-over-HTTP + real pages route + per-tenant opt-out admin surface).
- `services/ingestion/` — **245 tests** (+7 from M1-QA-02's tenant-isolation property tests on `InMemoryPageStore`) — Connector + parsers + chunker/embedder + classifier (with 429/5xx retry + catch-all annotation in prompt) + ontology inducer + wiki page builder.
- `services/meta-mcp/` — **179 tests** (+8 from M1-QA-03 privacy-boundary property tests; +2 unannounced from PR #11 CI flake fix earlier) — Privacy checkers + audit log + signature collector + meta-store + skill writer + skill applier + privacy-boundary property tests.
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

## Autonomous agents status (2026-05-26)

Both autonomous agents are currently OFF pending Josh's disposition decisions.

- **Cowork `vw-overnight` cron** — PAUSED via `mcp__scheduled-tasks__update_scheduled_task`. Was firing every 4h; had hit 12 consecutive no-ops since safe list was exhausted via `d906ce9` (2026-05-24, M1-QA-03). To resume: re-enable from the Cowork Tasks panel (needs a re-stocked safe list to be productive).
- **VM `versawiki-orchestrator` container** — STOPPED via `docker stop` on `project-mcp-server`. Was in `act` mode, self-paused on `$20/day` spend cap after opening 19 duplicate PRs (now all closed). To resume: needs (a) act/observe/disable decision, (b) SMTP escalation verification, (c) ideally a fresh safe list. See `notes/orchestrator.md` for forensic diary.

Until both are decided, no autonomous work happens. Interactive sessions are unaffected.

## Blockers awaiting Josh

- (none code-wise — all keys we have are in)
- Pending operations decisions: OPS-04 orchestrator disposition (act / observe / disable + SMTP verification), Apple Developer signup (OPS-02), Florida LLC filing (OPS-03), safe-list re-stock if autonomous overnight work should resume

## Next interactive tickets (morning, in order of leverage)

1. **OPS-04 disposition decision** — orchestrator deployed and stopped. Decide whether to resume in act mode (after SMTP verification + safe-list re-stock), demote to observe mode, or disable until M1 deploy is closer. ~10 min once chosen.
2. **M1-QA-01 end-to-end smoke against a real corpus** — now possible with both keys + ING-05. Point it at the prior MCP repo's docs as a corpus and verify the whole pipeline produces pages.
3. **M1-CS-03/04 wire support agent to admin API + SMTP** — gets customer support actually functional. (Also: doing M1-CS-04 first would give the orchestrator a known-good SMTP path to reuse, closing the OPS-04 escalation gap as a side-effect.)

## Quick links

- `README.md`, `ROADMAP.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, `ARCHITECTURE-LAYOUT.md`
- `docs/architecture/{stack,v1,domain-observation-v1}.md`
- `docs/research/{landscape,ontology,prior-art}.md`
- `docs/operations/*.md`
- `services/{api,ingestion,meta-mcp,support-agent}/`
- `notes/*` — per-role working logs

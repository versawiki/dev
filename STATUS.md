# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Current milestone

**M1 — Local-folder ingestion (headless).** 461 tests passing across three services. End-to-end backend complete (auth + provisioner + query + MCP endpoint), ingestion complete through ontology induction, meta-MCP learning loop closed read AND write.

## Last session summary (2026-05-22 → 2026-05-23, Waves 2-6)

Six interactive waves landed in one long session.

**Per-service current state:**

- `services/api/` — **115 tests** — FastAPI skeleton, API-key auth (argon2, hex tokens), Postgres tenant provisioner (CREATE SCHEMA + role + Alembic), query API v1 (`/query`, `/pages`, `/ontology` with tenant-scope-before-existence), MCP-over-HTTP endpoint (`search`, `read_page`, `read_chunk`, `list_ontology` over JSON-RPC + SSE).
- `services/ingestion/` — **180 tests** — Connector Protocol + LocalFolderConnector + 3 lifted parsers + registry, RecursiveCharacterSplitter + EmbeddingProvider (OpenAI + stub, 1024 dim), LLM document classifier with uncertainty signals, ontology inducer (SimpleEmbeddingClusterer + connected-components fallbacks where BERTopic/Leiden can't install).
- `services/meta-mcp/` — **166 tests** — DomainObservation Pydantic schemas, 5-stage privacy checker pipeline + tenant audit log, 8 compute_* signature functions + SignatureCollector + FileMetaStore, SignatureAggregator + LLM SkillWriter + text-checker-gated commit, SkillApplier + matcher + prompt injector + cache.

**Learning loop closed end-to-end:**

```
parse → chunk → embed → classify →
  emit (signature) → SignatureCollector → MCP-01a CheckerPipeline → FileMetaStore →
SignatureAggregator → SkillWriter (LLM) → text checker → skills/<domain>/...md → git commit →
SkillApplier reads on next ingestion → matched skill text prepended to LLM prompts
```

Every byte that crosses the tenant boundary, in either direction, goes through a privacy checker. **Four load-bearing privacy tests now green:**

1. `services/meta-mcp/tests/test_audit_log.py::test_write_never_includes_payload_bytes`
2. `services/meta-mcp/tests/test_collector_blocked_by_checker.py::test_phone_shaped_anon_id_is_rejected_by_pii_stage`
3. `services/meta-mcp/tests/test_skill_writer_blocked_by_checker.py::test_checker_rejects_skill_text_and_no_file_is_written` (parametrized × 6 poison bodies)
4. `services/meta-mcp/tests/test_skill_applier_opt_out.py::test_opt_out_returns_none_and_does_not_populate_cache`

## In flight

- (none — session wrapping for sleep)

## Blockers awaiting Josh

- (none)

## Overnight cron is live

A scheduled task runs every 4 hours. It picks one ticket from the "Overnight safe list" below, spawns ONE specialist, runs tests, commits + pushes only if green, updates this file. If anything is ambiguous, it STOPS and writes to `notes/orchestrator.md` for the morning. The PAT lives in the gitignored `.vw-cron-token` (never committed).

**Overnight safe list** (small scope, low risk, parallel-safe):

- `M1-ING-03b` — Classifier retry on LLM 429/5xx (isolated, ~30 lines).
- `M1-ING-03c` — Taxonomy `(catch-all)` annotation in classifier prompt (~10 lines).
- `M1-MCP-01a-fix` — `branching_factor_p50/p95` numeric checker: allow real values >1 (un-xfail the test).
- `M1-MCP-05` — Per-tenant opt-out flag API + persistence (gate already honored in collector + applier).
- `M1-QA-01` — End-to-end smoke harness in `tests/e2e/`.
- `M1-QA-02` — Tenant-isolation property tests.
- `M1-QA-03` — Privacy-boundary property tests.

**NOT for overnight** (interactive only): BE-04 retrofits, ING-05/06, anything cross-service.

## Next big interactive ticket (morning)

`M1-ING-05` Wiki page builder. Stale-on-event materialisation. Flips `pages.get_page` from always-404 to a real lookup, which then activates BE-05's `read_page` MCP tool. After ING-05 lands, end-to-end "ingest a folder → query the wiki" works for real.

## Quick links

- `README.md`, `ROADMAP.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, `ARCHITECTURE-LAYOUT.md`
- `docs/architecture/{stack,v1,domain-observation-v1}.md`
- `docs/research/{landscape,ontology,prior-art}.md`
- `services/api/` — full M1 surface (BE-01..05)
- `services/ingestion/` — connector + parsers + chunker + classifier + ontology (ING-01..04)
- `services/meta-mcp/` — checkers + collector + store + writer + applier (MCP-01a, 02, 03, 04)
- `notes/*` — per-role working logs

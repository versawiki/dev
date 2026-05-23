# Orchestrator notes

_The Orchestrator's running diary. Read top entry before deciding what to spawn._

## 2026-05-23 (Wave 5 integration)

**Spawned in parallel:** Backend (M1-BE-04 query routes), Ingestion (M1-ING-03 LLM classifier), MCP-builder (M1-MCP-03 skill writer).

**All three returned strong, non-overlapping work. Test deltas:**

- api: 77 -> 94 (+17 BE-04: query/pages/ontology routes + tenant scope + embed dep)
- ingestion: 90 -> 133 (+43 ING-03: classifier, alternatives, uncertainty signals)
- meta-mcp: 106 -> 141 (+35 MCP-03: aggregator, thresholds, LLM writer, text-checker, versioning, git commit)

**Total now: 368 tests passing across three services.**

**Architectural milestone:** the learning loop is operationally closed end-to-end:

```
parse -> chunk -> embed -> classify ->
  (ClassifierUncertainty + DocumentTypeDistribution + ... signatures) ->
SignatureCollector (gates via MCP-01a CheckerPipeline) ->
  FileMetaStore ->
SignatureAggregator (groups by domain/kind, thresholds) ->
SkillWriter (LLM draft) ->
  Text-shaped CheckerPipeline (built on MCP-01a primitives) ->
services/meta-mcp/skills/<domain>/<kind>__<slug>__v<n>.md ->
  git commit
```

Every byte that crosses the tenant boundary, in either direction (signature emit, skill apply), goes through a checker.

**Three load-bearing privacy tests now green:**

1. `test_audit_log.py::test_write_never_includes_payload_bytes` (MCP-01a — audit log never persists offending payload).
2. `test_collector_blocked_by_checker.py::test_phone_shaped_anon_id_is_rejected_by_pii_stage` (MCP-02 — collector gate is the single chokepoint).
3. `test_skill_writer_blocked_by_checker.py::test_checker_rejects_skill_text_and_no_file_is_written` parametrized over 6 poison bodies (MCP-03 — skill text gate before disk).

If any of these silently pass wrong, the product's positioning collapses.

**Source bugs surfaced this wave, all captured for cleanup (not blocking):**

- MCP-01a CheckerPipeline is envelope-shaped; MCP-03 needed a text-shaped variant. Built `skill_text_check.check_skill_text()` reusing the same primitives — sound but worth refactoring into a single dispatch surface in M1-MCP-04 or a fix ticket.
- ING-03 classifier LLM providers don't retry on 429/5xx (embedder does). Captured as M1-ING-03b.
- ING-03 prompt template doesn't annotate which taxonomy entry is the catch-all. Captured as M1-ING-03c.

**Next: Wave 6 — BE-05 (MCP endpoint, reusing BE-04 deps) + ING-04 (ontology inducer) + MCP-04 (skill applier).** All independent.

---

# Orchestrator notes

_The Orchestrator's running diary. Read top entry before deciding what to spawn._

## 2026-05-22 (Wave 4 integration)

**Spawned in parallel:** Backend (M1-BE-03 tenant provisioner), Ingestion (M1-ING-02 chunker+embedder — fully net-new), MCP-builder (M1-MCP-02 signature collector).

**All three returned strong, mutually-non-overlapping work. Test counts:**

- api: 27 -> 77 (+50 BE-03 unit tests; 2 integration skips for no-DB sandbox)
- ingestion: 40 -> 90 (+50 ING-02 chunker/embedding/pipeline tests)
- meta-mcp: 41 -> 106 (+65 MCP-02 signatures/collector/store tests)

**Total now: 273 tests passing across the three services.**

**Privacy story is now fully operational, not just documented.** The MCP-02 collector is the single chokepoint between raw ingestion events and the meta-store; it routes everything through the MCP-01a CheckerPipeline before persistence. The load-bearing privacy test is `test_collector_blocked_by_checker.py::test_phone_shaped_anon_id_is_rejected_by_pii_stage` — if that ever flips to passing wrong, the collector has dropped its gate and the privacy invariant is broken.

**Two source bugs in MCP-01a fixed inline by the MCP-02 agent while building on top:**
1. PII regex matched ~3% of random UUIDv4s as phone numbers — now whitelists UUID-shape strings.
2. `FileMetaStore` `_parse_iso_z` tolerates Pydantic's `Z` suffix on Python 3.10 (sandbox) where `datetime.fromisoformat` is strict.

**Carried-over xfail** (from MCP-01a): `branching_factor_p50/p95` capped at [0,1] though spec allows real values >1. Tracked in icebox as `M1-MCP-01a-fix`. Non-privacy bug; doesn't block Wave 5.

**Backend agent suggested 3 follow-ups, added to icebox:** BE-03b (CI Postgres integration), BE-03c (per-request SET ROLE + search_path dep), provisioner idempotency/"ensure" mode.

**Next: Wave 5 — BE-04 (query API routes wired to per-tenant DB) + ING-03 (LLM document classifier) + MCP-03 (skill writer).** All three independent.

---

# Orchestrator notes

_The Orchestrator's running diary. Read top entry before deciding what to spawn._

## 2026-05-22 (Wave 3 integration — second pass)

**First-pass Wave 3 was killed mid-flight by a session limit before agents reported back, but the agents had committed real code to disk before dying.** On resume (Josh upgraded to Max), audited the disk state:

- BE-02 source was complete (auth/, routers/admin/api_keys.py, schemas/api_key.py, 2 test files) but had 4 failing tests — all cascaded from a `secrets.token_urlsafe()` producing prefixes/secrets with `_` characters, making the `vw_<prefix>_<secret>` on-wire format ambiguous. Fixed the generator (use `secrets.token_hex`) and tightened `parse_token` to enforce min length on each part. 27/27 now green.
- ING-01 source was complete but had no tests written. Spawned a focused ING-01 finisher subagent who wrote 40 tests (8 connector + 8 parser + 24 registry). All green. No source bugs.
- MCP-01a source was 70% there: checkers present, schema present, but missing pyproject.toml/README/audit module/tests. Spawned an MCP-01a finisher subagent who wrote pyproject + audit/ + 41 tests. 41 pass / 1 skip (spaCy unavailable in sandbox) / 1 xfail (non-privacy bug in numeric.py: branching_factor_p50/p95 mistakenly capped at [0,1]). Captured the xfail bug for QA.

**Total now: 108 tests passing across services/api, services/ingestion, services/meta-mcp.** The 3 services are independent packages — each has its own pyproject.toml and tests cleanly.

**Privacy invariant operationally enforced:** `services/meta-mcp/tests/test_audit_log.py::test_write_never_includes_payload_bytes` asserts the offending payload is never written to disk. Silent passage = privacy breach. Green.

**No new DECISIONS.md entries needed.** All choices fell within existing decisions or were small implementation calls.

**Next: Wave 4 — BE-03 (tenant schema provisioner) + ING-02 (chunker/embedder — net-new) + MCP-02 (signature collector). All three independent.**

---

# Orchestrator notes

_The Orchestrator's running diary. Read top entry before deciding what to spawn._

## 2026-05-22 (Wave 2 integration)

**Spawned in parallel:** Researcher (M0-06 prior-repo audit), Architect (M1-MCP-01 DomainObservation), Backend (M1-BE-01 FastAPI skeleton).

**All three returned coherent, high-quality output.** Three big takeaways:

1. **Prior MCPs are vector-RAG in name only.** Researcher's file-level audit caught what live-probes couldn't: the schema column exists but is never written, `sentence-transformers` is commented out in requirements, search is pure `ILIKE`. M1-ING-02 (chunker + embedder + vector retrieval) is now flagged as fully net-new — no prior code to lift. Recorded as a planning fact in DECISIONS.md.
2. **DomainObservation v1 is tight.** 8 payload variants, discriminated union, no `str` field accepts arbitrary text anywhere, numerics-as-buckets only. Architect's 5 open questions were each within day-or-two-rework and reversible, so accepted all his recommendations as Orchestrator calls. Logged together as one DECISIONS.md entry to avoid log noise.
3. **FastAPI skeleton is healthy.** 8/8 tests pass. The most important thing BE-01 did wasn't code — it locked the downstream patterns (error envelope, settings_dep, auth dep seam) that BE-02/03/04/05 plug into.

**Operational lesson (extended file-sync-gap memory):** Backend agent hit a NEW variant of the file-sync bug — the `Edit` tool silently *truncated* multiple Python files it had just created via `Write` in the same session. Only caught by `pytest` returning `SyntaxError`. Updated `versawiki-file-sync-gap.md` memory with the stronger rule: spawned subagents should be told explicitly to use bash heredoc for ANY modification to an existing file, including files they themselves created earlier in the same run.

**Next-session-equivalent plan (this session continues):**

- Spawn Wave 3 in parallel: BE-02 (auth middleware on top of the seam), ING-01 (connector + 3 parser lifts), MCP-01a (privacy static checkers).
- After integration: commit + push. If energy remains, Wave 4 = BE-03 (tenant schema provisioner) + ING-02 (chunker/embedder — net-new) + MCP-02 (signature collector).

---

# Orchestrator notes

_The Orchestrator's running diary. Read top entry before deciding what to spawn._

## 2026-05-22 (session wrap)

**Josh's privacy-bar answer (verbatim, paraphrased for the log):** no customer names / figures / files / quotes cross the boundary; naming conventions / syntax / organizational structures / data relationships / procedures / generally applicable principles may cross. Captured in `DECISIONS.md` and in memory (`versawiki-privacy-boundary.md`).

**Prior MCP repo:** Mounted from `C:\Users\joshu\Downloads\project-mcp-server`. Quick snapshot looks like a Python+Docker MCP server — 20 .py files, server.py at 18KB, dirs match the live-probes' inferences (parsers, schema, tools, config, deploy). Researcher to do a real audit next session as `M0-06`.

**GitHub:** No PAT yet. Bundle `versawiki-initial.bundle` delivered to Josh's outputs folder along with `PUSH-TO-GITHUB.md` instructions. He'll push from laptop; will provide a PAT in a future session for ongoing pushes.

**Sessions's net new decisions:** 1 (the privacy boundary). All other decisions were already locked earlier in the session.

**Backlog refined:** Added M1-MCP-01a (privacy static checkers), M1-MCP-05 (per-tenant opt-out), M1-QA-03 (privacy-boundary property tests). M0-06 (prior repo audit) is now top of Ready.

**Next session plan:** Orchestrator should immediately spawn three specialists in parallel — Researcher (M0-06), Architect (M1-MCP-01), Backend (M1-BE-01) — none of which block each other. After they return: Orchestrator reconciles, queues the next wave (likely Ingestion ING-01 + Backend BE-02), and reports.

---

## 2026-05-22 (end of first integration)

**Spawned and integrated:** Architect (M0-01, M0-02) + Researcher (M0-03, M0-04, M0-05) in parallel.

**Reconciled:** Architect proposed Python + FastAPI + Postgres/pgvector. Researcher independently confirmed ~70% reuse from the prior `project-docs-*` MCPs (also Python). Stack call was overdetermined — locked it.

**Decisions made without escalating** (all day-or-two-rework or cheaper):

- Stack bundle (Python/FastAPI, Postgres+pgvector HNSW, Next.js, Tauri, Expo, RQ, Anthropic+OpenAI, Fly+Neon+R2).
- Tenant isolation = schema-per-tenant with per-tenant Postgres roles; enterprise = dedicated DB.
- MCP transport = MCP-over-HTTP streamable.
- Embedding plumbing: dim 1024 locked; start hosted OpenAI text-embedding-3-large@1024; swap to self-hosted (bge-m3 / nomic-embed-text-v2) before M3.
- Ontology pipeline: reimplement light on top of pgvector; no GraphRAG wholesale adoption.
- No graph DB, no fine-tuning, AEC starter taxonomy in M1.

**Escalated to Josh:**

- Meta-MCP cross-tenant privacy bar — answered (see top entry).
- Prior MCP-server repo URL — answered (see top entry).
- GitHub push credential — bundle workflow set up; PAT later.

**Operational lesson learned (saved to memory):** Cowork's Write/Edit tools overwrite files in a way that doesn't propagate to the bash mount git uses. Always use bash heredoc for edits to existing files; reserve the Cowork file tools for new-file creation.

---

## 2026-05-22 (start of session)

Team office bootstrapped from a blank repo. Coordination contract (README, ROADMAP, BACKLOG, STATUS, DECISIONS, AGENTS) is in place. About to spawn first wave: Architect + Researcher in parallel.

**Open question for Josh (low-stakes, deciding myself):** No GitHub push credential yet. Decision: keep committing locally until Josh provides a PAT. Flagged in `STATUS.md` blockers.

**Watch for:** Architect's stack recommendation. Don't lock it in `DECISIONS.md` until the Researcher's landscape and prior-art reports come back — they may influence framework choice (e.g., if the prior MCP-server code is Python, that argues for Python backend).

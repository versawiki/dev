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

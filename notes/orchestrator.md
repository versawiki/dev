# Orchestrator notes

_The Orchestrator's running diary. Read top entry before deciding what to spawn._

## 2026-05-22 (end of session)

**Spawned and integrated:** Architect (M0-01, M0-02) + Researcher (M0-03, M0-04, M0-05) in parallel.

**Reconciled:** Architect proposed Python + FastAPI + Postgres/pgvector. Researcher independently confirmed ~70% reuse from the prior `project-docs-*` MCPs (also Python). Stack call was overdetermined — locked it.

**Decisions made without escalating** (all day-or-two-rework or cheaper):

- Stack bundle (Python/FastAPI, Postgres+pgvector HNSW, Next.js, Tauri, Expo, RQ, Anthropic+OpenAI, Fly+Neon+R2).
- Tenant isolation = schema-per-tenant with per-tenant Postgres roles; enterprise = dedicated DB.
- MCP transport = MCP-over-HTTP streamable.
- Embedding plumbing: dim 1024 locked; start hosted OpenAI text-embedding-3-large@1024; swap to self-hosted (bge-m3 / nomic-embed-text-v2) before M3.
- Ontology pipeline: reimplement light on top of pgvector; no GraphRAG wholesale adoption.
- No graph DB, no fine-tuning, AEC starter taxonomy in M1.

**Escalating to Josh (rework cost > day-or-two):**

- Meta-MCP cross-tenant privacy bar (strict vs loose). Shapes M1 logging schema and is positioning-load-bearing. My recommendation: strict for v1.

**Other asks for Josh (unblockers, not decisions):**

- Prior MCP-server repo URL — for Researcher's real code audit.
- GitHub push credential — local commits accumulating.

**M1 backlog queued:** 17 tickets. Critical path: BE-01 (skeleton) -> BE-02/03 (auth, schema) -> ING-01/02 (connector, embed) -> ING-03/04 (classify, ontology) -> ING-05 (pages) -> BE-04/05 (query API, MCP endpoint). MCP-01 (DomainObservation contract) is the highest-leverage single ticket and is blocked until the privacy bar decision.

**Watch for next session:**

- If Josh confirms strict privacy bar: spawn Architect for `domain-observation-v1.md` AND Backend for BE-01 in parallel.
- If Josh provides prior repo URL: spawn Researcher for the audit BEFORE writing any ingestion code that overlaps the prior MCPs' patterns.
- If credential lands: push the accumulated commits.

**Operational lesson learned (saved to memory):** Cowork's Write/Edit tools overwrite files in a way that doesn't propagate to the bash mount git uses. Always use bash heredoc for edits to existing files; reserve the Cowork file tools for new-file creation.

---

## 2026-05-22 (start of session)

Team office bootstrapped from a blank repo. Coordination contract (README, ROADMAP, BACKLOG, STATUS, DECISIONS, AGENTS) is in place. About to spawn first wave: Architect + Researcher in parallel.

**Open question for Josh (low-stakes, deciding myself):** No GitHub push credential yet. Decision: keep committing locally until Josh provides a PAT. Flagged in `STATUS.md` blockers.

**Watch for:** Architect's stack recommendation. Don't lock it in `DECISIONS.md` until the Researcher's landscape and prior-art reports come back — they may influence framework choice (e.g., if the prior MCP-server code is Python, that argues for Python backend).

# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Current milestone

**M1 — Local-folder ingestion (headless).** M0 fully closed. FastAPI skeleton landed. DomainObservation contract locked. Prior code audited file-by-file.

## Last session summary (2026-05-22, continuing)

**Wave 2 (3 parallel specialists) returned and integrated:**

- **Architect** wrote `docs/architecture/domain-observation-v1.md` (561 lines, 8 payload variants, discriminated union, all `frozen=True`, no free-form strings, numerics-as-buckets). Surfaced 5 open questions; Orchestrator accepted all 5 of his recommendations (reversible inside v1.x).
- **Researcher** updated `docs/research/prior-art.md` with file-by-file audit of `C:\Users\joshu\Downloads\project-mcp-server` (27 files: 3 REUSE / 11 ADAPT / 13 REPLACE). Big surprise: prior MCPs are vector-RAG in name only — `embedding BYTEA` column never written, `sentence-transformers` commented out, search is pure `ILIKE`. Recorded as its own decision/observation in DECISIONS.md.
- **Backend** built `services/api/` (FastAPI skeleton, OpenAPI export, 8/8 tests passing). Locked downstream patterns: error envelope, structlog-on-stderr, settings_dep, auth dep seam.

**Repo is now at:** github.com/versawiki/dev (will push after this commit).

## In flight

- (none — about to spawn Wave 3)

## Blockers awaiting Josh

- (none — token is in session memory; all decisions either locked or appropriately escalated and answered)

## Next intended action (this session)

**Wave 3 — three more parallel specialists:**

1. **Backend** — `M1-BE-02` API-key auth middleware. Drops into the dep seam BE-01 already left.
2. **Ingestion** — `M1-ING-01` Connector interface + local-folder connector. Lifts 3 parser files from the prior repo per the M0-06 audit.
3. **MCP-builder** — `M1-MCP-01a` Privacy static checkers. Implements the 5-stage pipeline specified in `domain-observation-v1.md` §5.

## Quick links

- `README.md` — mission
- `ROADMAP.md` — milestones
- `BACKLOG.md` — what's ready, in flight, and done
- `DECISIONS.md` — what we've locked and why
- `AGENTS.md` — team roster and operating rules
- `ARCHITECTURE-LAYOUT.md` — where everything lives in the repo
- `docs/architecture/stack.md` — locked stack
- `docs/architecture/v1.md` — v1 system design
- `docs/architecture/domain-observation-v1.md` — meta-MCP wire contract
- `docs/research/*` — landscape, ontology, prior-art (now includes M0-06 real audit)
- `services/api/` — FastAPI skeleton (BE-01)
- `notes/*` — per-role working logs

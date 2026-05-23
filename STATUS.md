# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Current milestone

**M0 — Foundations.** Stack locked. v1 system design drafted. Landscape + ontology + prior-art research banked. M1 backlog populated (17 tickets).

## Last session summary (2026-05-22)

- Repo bootstrap committed: `1f65311` (18 files, the team coordination contract).
- First-wave specialists spawned in parallel:
  - **Architect** produced `docs/architecture/stack.md` and `docs/architecture/v1.md`. Headline picks: Python+FastAPI / Postgres+pgvector / Next.js / Tauri / Expo / Anthropic+OpenAI / Fly+Neon+R2.
  - **Researcher** produced `docs/research/landscape.md` (13-product survey), `docs/research/ontology.md` (recommended M1 pipeline), `docs/research/prior-art.md` (live probes against the four `project-docs-*` MCPs; ~70% reusable shape).
- Orchestrator locked in 6 new decisions in `DECISIONS.md` (stack, tenant isolation, MCP transport, embedding plumbing, ontology pipeline, smaller-bundle calls).
- M1 backlog populated: 5 Backend tickets, 6 Ingestion tickets, 4 Meta-MCP tickets, 2 QA tickets.

## In flight

- (none — awaiting Josh's input before spawning the next wave)

## Blockers awaiting Josh

1. **Meta-MCP cross-tenant privacy bar** — strict (no raw text or labels cross the tenant boundary; only anonymized structural signatures) vs. loose (labels can cross, better cross-customer learning). Both specialists flagged this independently. It shapes the M1 logging schema and the `DomainObservation` event contract (ticket `M1-MCP-01`), so we can't build the meta-MCP path until this is settled. Orchestrator's recommendation: **strict for v1, opt-in loosening later for enterprise tenants who explicitly consent.**
2. **Prior MCP-server repo URL** — Researcher's `M0-05` was constrained to probing the live MCP tools and reading the `domain-expert-mcps` skill. To do a real code-reuse audit, we need the repo URL. Required filename patterns are at the end of `docs/research/prior-art.md`.
3. **GitHub push credential** — Personal Access Token or connected GitHub MCP. Until then, commits stack up locally on the work-tree and are not visible on `github.com/versawiki/dev`.

## Next intended action (after Josh unblocks)

- **If Josh confirms "strict" privacy bar:** spawn Architect again to write `docs/architecture/domain-observation-v1.md` (the wire contract that crosses the tenant->meta boundary). Parallel: spawn Backend to begin `M1-BE-01` (FastAPI skeleton) since that has no privacy-bar dependency.
- **If Josh provides the prior repo URL:** spawn Researcher to do a real code audit and update `docs/research/prior-art.md`.
- **If Josh provides the GitHub push credential:** Orchestrator runs `git push origin main` and stops accumulating local commits.

## Quick links

- `README.md` — mission
- `ROADMAP.md` — milestones
- `BACKLOG.md` — what's ready, in flight, and done
- `DECISIONS.md` — what we've locked and why
- `AGENTS.md` — team roster and operating rules
- `docs/architecture/stack.md` — locked stack
- `docs/architecture/v1.md` — v1 system design
- `docs/research/*` — landscape, ontology, prior art
- `notes/*` — per-role working logs

# Agent team roster

Read this if you're an agent being spawned into versawiki. It is your job description and the team's operating contract.

## How the team works

1. **The Orchestrator (Claude) reads everything first.** Every session starts with the Orchestrator reading `STATUS.md`, `BACKLOG.md`, the relevant `notes/*.md`, and the user's request.
2. **The Orchestrator decides what to spawn.** Specialists are subagents (Task tool). Independent work runs in parallel. Dependent work is sequenced.
3. **Every specialist writes back to `notes/<role>.md`** before returning. That's how the next session picks up where this one left off.
4. **Decisions go to `DECISIONS.md`.** The Orchestrator records what was decided, by whom, and why. Day-or-two-rework-stakes calls don't need Josh's signoff; bigger calls do.
5. **Commits happen at the end of the session.** The Orchestrator stages, commits with a descriptive message, and pushes (once a credential exists).

## Escalation rule

The Orchestrator asks Josh before acting only when a wrong choice would cost a day or two of rework. Anything cheaper, the Orchestrator decides and records the call in `DECISIONS.md`. Josh monitors via mobile and desktop and can override anything.

## Roles

### Orchestrator
**Played by:** Claude in the chat session.
**Mission:** Read project state, decide what's next, spawn specialists, integrate their output, report to Josh.
**Inputs:** `STATUS.md`, `BACKLOG.md`, all `notes/*.md`, latest user message.
**Outputs:** Updated `STATUS.md`, `BACKLOG.md`, `DECISIONS.md`; git commits; a concise message back to Josh.
**Spawn signal:** Always — first thing every session.

### Architect
**Mission:** System design, API contracts, data model, security model, tech-stack choices. Owns `docs/architecture/`.
**Inputs:** `ROADMAP.md`, recent decisions, Researcher's findings if available.
**Outputs:** Architecture markdown files, proposed decision entries, backlog tickets for the Backend and MCP-builder roles.
**Spawn when:** A new milestone opens, a major contract needs definition, or two specialists report a contract conflict.

### Backend / API engineer
**Mission:** Implement the ingestion service, query API, auth, tenant isolation, the API-key-gated MCP-serving endpoint.
**Inputs:** Architect's contracts in `docs/architecture/`, BACKLOG tickets tagged Backend.
**Outputs:** Code under `services/api/`, tests, updated `notes/backend.md`.
**Spawn when:** A Backend-tagged ticket is Ready and contracts exist.

### Internal MCP builder
**Mission:** Build the self-improving meta-MCP that learns ingestion patterns and writes skills/markdown notes to itself. This is the novel core of versawiki — treat it with care.
**Inputs:** Architect's contracts, Ingestion engineer's classifier output, prior MCP-server code surveyed by the Researcher.
**Outputs:** Code under `services/meta-mcp/`, learned skill files under `services/meta-mcp/skills/`, updated `notes/mcp-builder.md`.
**Spawn when:** Backend has a working ingestion path and the Ingestion engineer has a v1 classifier.

### Ingestion & ontology engineer
**Mission:** Document classification, ontology induction, connector adapters (local folder first, then Drive/OneDrive/Dropbox/Box/iCloud), query-driven re-indexing.
**Inputs:** Researcher's ontology findings, Architect's data model, sample documents.
**Outputs:** Code under `services/ingestion/`, connector adapters under `services/ingestion/connectors/`, `notes/ingestion.md`.
**Spawn when:** Architect has settled on a data model.

### Cross-platform UI engineer
**Mission:** Web app (primary), desktop wrapper, mobile app. Maximize shared code. Initially one engineer; may split into web/desktop and mobile once surface area justifies it.
**Inputs:** Architect's API contracts, design constraints from `DECISIONS.md`.
**Outputs:** Code under `apps/web/`, `apps/desktop/`, `apps/mobile/`. `notes/ui.md`.
**Spawn when:** API contracts exist and at least a stub backend is queryable.

### Researcher
**Mission:** Web research on file-storage APIs, wiki ontologies, similar products, MCP patterns, embedding models, anything the Architect or builders need outside their head.
**Inputs:** Open questions in `notes/<role>.md` files; explicit research tickets.
**Outputs:** Markdown files in `docs/research/`, updates to `notes/researcher.md` with summaries and links.
**Spawn when:** Any specialist flags an open question, or in parallel with the Architect to compress design loops.

### QA / integration
**Mission:** Build and test runs, contract drift detection between services, end-to-end smoke tests, performance regression watch.
**Inputs:** Code from all builder roles.
**Outputs:** Test reports, CI config, `notes/qa.md`.
**Spawn when:** Two or more services exist, or before any release-tagged milestone exit.

## Spawn template (for the Orchestrator)

When spawning a specialist, include in the Task prompt:

1. The role this agent is playing (copy from above)
2. The exact ticket(s) being worked
3. The relevant `notes/<role>.md` content
4. The escalation rule
5. The expected output (files to write, decisions to propose)
6. A reminder to update `notes/<role>.md` before returning

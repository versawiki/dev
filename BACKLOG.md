# Backlog

Prioritized top-to-bottom within each section. The Orchestrator pulls from "Ready" when spawning specialists. Items become "In flight" when a specialist is working on them, "Done" when merged.

Each ticket: `ID — title (role) — one-line description`. Heavier specs go in `docs/tickets/<id>.md`.

## Ready (M0)

- `M0-01 — Recommend tech stack (Architect)` — Backend, web, desktop, mobile. Concrete versions. Justify each in 2–4 sentences. Write to `docs/architecture/stack.md` and propose a decision entry.
- `M0-02 — Draft v1 system design (Architect)` — Services, data model, auth model, MCP-serving shape. Write to `docs/architecture/v1.md`.
- `M0-03 — Survey existing file-storage-to-wiki products (Researcher)` — Mem, Glean, Notion AI, Sana, Guru, etc. What do they do well; where do they fall short on the private-MCP angle. Write to `docs/research/landscape.md`.
- `M0-04 — Survey ontology-induction approaches for mixed-document corpora (Researcher)` — Write to `docs/research/ontology.md`.
- `M0-05 — Catalog prior MCP-server code worth reusing (Researcher)` — The four `project-docs-*` MCPs in the tool list share an ingestion + embedding + Postgres pattern. Document what's reusable for versawiki. Write to `docs/research/prior-art.md`.

## In flight

- (none)

## Done

- (none)

## Icebox (not yet prioritized)

- Cross-customer pattern sharing protocol
- Mobile read-only viewer
- Billing & API key issuance UI

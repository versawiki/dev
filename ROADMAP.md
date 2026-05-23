# versawiki roadmap

Milestones, not dates. The Orchestrator promotes the next milestone when the current one passes its exit criteria.

## M0 — Foundations (current)

The team office exists, the architect has proposed a stack, and we have a one-page spec for the ingestion pipeline. No code yet.

Exit criteria:
- `docs/architecture/v1.md` exists and is reviewed
- Initial tech stack is locked in `DECISIONS.md`
- `BACKLOG.md` has at least 10 well-formed M1 tickets

## M1 — Local-folder ingestion, headless

A backend service that, given a local folder path, walks the tree, classifies documents, builds an initial ontology, embeds chunks, and stores everything in Postgres + a vector store. Query is via CLI or HTTP.

Why local first: no OAuth, no rate limits, fastest path to a working ingestion → wiki demo. Validates the hard parts (classification, ontology induction, query-driven re-indexing) without connector complexity.

Exit criteria:
- Point the service at a folder, get a queryable wiki out the other side
- API key auth working
- Per-tenant isolation enforced
- The "invisible internal MCP" that learns from ingestion is writing notes to itself

## M2 — Google Drive connector + web UI

OAuth-gated Drive ingestion. A web app that walks a new customer through "pick a drive, pick folders, grant scope, watch the wiki build."

## M3 — Desktop app

Tauri (likely — pending architect's recommendation) wrapper that runs the local-folder ingestion path in-process for private corpora users don't want to send to the cloud.

## M4 — OneDrive / SharePoint connector

The largest enterprise footprint and where most companies' real "wiki of record" actually lives.

## M5 — Mobile app

React Native or Flutter (pending architect). Read-only wiki + ask-the-wiki chat. Ingestion stays on web/desktop.

## M6 — Dropbox / Box, then iCloud Files

Lower-priority connectors, added once the core pipeline is hardened.

## M7 — Cross-customer pattern sharing

The meta-MCP starts proposing structural improvements to new tenants based on patterns learned from prior tenants in the same domain. Customer data remains isolated; only learned *shapes* of organization are shared.

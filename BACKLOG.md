# Backlog

Prioritized top-to-bottom within each section.

## Ready (M1 — what's left)

**Ingestion**

- `M1-ING-05 — Wiki page builder (Ingestion)` — Stale-on-event materialisation; one page per ontology node + per cluster. Flips `pages.get_page` from always-404 to a real lookup, activates BE-05's `read_page` MCP tool.
- `M1-ING-06 — Query-driven re-indexing scheduler (Ingestion)`.

**Meta-MCP**

- `M1-MCP-05 — Per-tenant opt-out (MCP-builder)` — Flag API + persistence.

**Customer Support (new)**

- `M1-CS-02 — Structured Anthropic tool-use (Support)` — Refactor to native tool-use loop.
- `M1-CS-03 — Wire admin API (Support)` — Connect agent actions to real BE-03 admin endpoints with a service token.
- `M1-CS-04 — SMTP outbound (Support)` — Postmark/SendGrid for sending replies.
- `M1-CS-05 — Notifier (Support)` — Slack/Telegram/email push when escalations land.
- `M1-CS-06 — Web chat widget (Support)` — Small React component for marketing site + app.
- `M1-CS-07 — Escalation review UI (Support)` — Tiny page for Josh to review/reply/close queued escalations.

**Operations (new — Josh-driven mostly)**

- `OPS-02 — Apple Developer + Google Play accounts` — Per `docs/operations/app-store-prep.md`.
- `OPS-03 — LLC + bank + EIN` — **Florida chosen.** File via Sunbiz.org ($125) + EIN from IRS (free) + Mercury bank account + registered agent. Skip Stripe Atlas (Delaware-only). See `docs/operations/llc-and-business.md` (Florida addendum).
- `OPS-04 — Claude Agent SDK orchestrator on the GCP VM` — Per `docs/operations/agent-sdk-spec.md`. ~3 working days when ready.
- `OPS-05 — Privacy policy + ToS + DPA drafts` — Termly/Iubenda templates, then lawyer review.
- `OPS-06 — Production infrastructure (Fly + Neon + R2 accounts)` — Just-in-time before M1 deploy.
- `OPS-07 — Stripe billing` — After LLC closes.

**QA**

- `M1-QA-01 — End-to-end smoke harness`.
- `M1-QA-02 — Tenant-isolation property tests`.
- `M1-QA-03 — Privacy-boundary property tests`.

## Overnight safe list (cron picks from here)

`M1-ING-03b`, `M1-ING-03c`, `M1-MCP-01a-fix`, `M1-MCP-05`, `M1-QA-01`, `M1-QA-02`, `M1-QA-03`. (None of the new OPS or CS tickets — they touch external systems / need credentials.)

## In flight

- (none)

## Done

- `M1-CS-01 — Customer support agent v1 (Support)` — `services/support-agent/`; 62 tests; safe/forbidden actions; PII redaction; cross-tenant block. Load-bearing tests: `test_cross_tenant_lookup_refused_and_audited_not_escalated`, `test_conversation_log_never_contains_cc_number`.
- `M1-MCP-04 — Skill applier (MCP-builder)`.
- `M1-ING-04 — Ontology inducer (Ingestion)`.
- `M1-BE-05 — MCP-over-HTTP endpoint (Backend)`.
- `M1-MCP-03 — Skill writer (MCP-builder)`.
- `M1-ING-03 — Document classifier (Ingestion)`.
- `M1-BE-04 — Query API routes (Backend)`.
- `M1-MCP-02 — Signature collector (MCP-builder)`.
- `M1-ING-02 — Chunker + embedder pipeline (Ingestion)`.
- `M1-BE-03 — Tenant schema provisioner (Backend)`.
- `M1-MCP-01a — Privacy static checkers (MCP-builder)`.
- `M1-ING-01 — Connector interface + local-folder connector (Ingestion)`.
- `M1-BE-02 — API-key auth middleware (Backend)`.
- `M1-BE-01 — FastAPI skeleton (Backend)`.
- `M1-MCP-01 — DomainObservation event schema (Architect)`.
- `OPS-01 — Cloudflare DNS migration` — Josh completed 2026-05-23; all 4 domains now on Cloudflare nameservers. Records + workers still to configure as services come online.
- `M0-01..06 — All M0 tickets done`.

## Icebox

- M1-BE-03b — PostgresTenantStore integration coverage.
- M1-BE-03c — Per-request `SET ROLE` / `search_path` dep.
- M1-BE-05b — Real chunks SQL in `tool_search` (needs pgvector activation).
- M1-MCP-04b — Real LLM matchers.
- Wire ING-04's OntologyInducer into a corpus-level orchestrator.
- Cross-customer pattern sharing protocol (M7).
- Mobile read-only viewer (M5).
- Billing & API key issuance UI.
- Desktop "private mode" embedded Python ingestion (M3).
- Drive / OneDrive / Dropbox / Box / iCloud connector tickets (M2, M4, M6).

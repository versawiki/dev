# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Current milestone

**M1 — Local-folder ingestion (headless)** + early Operations + Customer Support tracks now open. **523 tests passing** across four services.

## Per-service current state

- `services/api/` — **115 tests** — Full M1 backend (skeleton + auth + provisioner + query routes + MCP-over-HTTP).
- `services/ingestion/` — **180 tests** — Connector + parsers + chunker/embedder + classifier + ontology inducer.
- `services/meta-mcp/` — **166 tests** — Privacy checkers + audit log + signature collector + meta-store + skill writer + skill applier.
- `services/support-agent/` — **62 tests** — Autonomous customer support: KB, safe/forbidden actions, PII redaction, cross-tenant block, email + web + API intake, escalation queue.

## Operations docs added (in `docs/operations/`)

For Josh to read in the morning. Each is action-oriented.

- `agent-sdk-spec.md` — Full architecture spec for moving from Cowork cron to a 24/7 Claude Agent SDK service on the existing GCP VM.
- `dns-cloudflare-migration.md` — Click-by-click for moving 4 domains from Namecheap to Cloudflare.
- `launch-readiness.md` — Tiered checklist (long lead → just-in-time → before-paying-customer → before-launch) with costs and times.
- `llc-and-business.md` — Stripe Atlas vs DIY vs Clerky; recommendation = Stripe Atlas; full 30-day startup checklist.
- `app-store-prep.md` — Apple Developer + Google Play accounts to start NOW; code signing decisions; deferrals.
- `customer-support-strategy.md` — How the "company runs without humans" target actually works in practice, with cost model, escalation routing, channel strategy, and what's left to ship the agent for production.

## Overnight cron status

Still live. Picks one ticket every 4 hours from the safe list. Will pause when the list is exhausted.

## Blockers awaiting Josh

- (none code-wise)
- Operational asks (drive each yourself; the docs above explain how):
  1. Cloudflare account + nameserver swap (~30 min)
  2. Apple Developer + Google Play signup (~1 hour, $124 total, 1-2 day Apple wait)
  3. LLC decision (Stripe Atlas recommended; ~1 week start-to-finish)
  4. Decide: continue with Cowork cron, or invest the ~3 days to set up the Agent SDK orchestrator on the VM

## Next big interactive ticket (morning)

`M1-ING-05` Wiki page builder — closes the end-to-end "ingest a folder → query a real wiki page" loop.

## Quick links

- `README.md`, `ROADMAP.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, `ARCHITECTURE-LAYOUT.md`
- `docs/architecture/{stack,v1,domain-observation-v1}.md`
- `docs/research/{landscape,ontology,prior-art}.md`
- `docs/operations/*.md` — **new this session**
- `services/api/`, `services/ingestion/`, `services/meta-mcp/`, `services/support-agent/`
- `notes/*` — per-role working logs

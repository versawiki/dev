# versawiki

A private, per-customer wiki built automatically from the documents a customer points at — local folders, Google Drive, OneDrive/SharePoint, Dropbox/Box, iCloud — and served to both humans (web, desktop, mobile) and LLMs (via a per-customer MCP and API-key-gated API) so that working context is one cheap query away instead of an expensive RAG round-trip.

The wiki is **versatile**: same backend serves humans browsing on their phone and agents pulling context mid-task. That's where the name comes from.

## What makes versawiki different

- **The wiki structures itself.** On ingestion, the system identifies what *kind* of corpus this is (engineering project docs, legal matter, personal research, codebase, recipes, whatever) and builds an ontology to fit. It doesn't impose a template.
- **It learns from queries.** Recurring query patterns reshape how the corpus is indexed and cross-linked. A wiki that nobody asks calendar questions of doesn't bother building a calendar view.
- **A private MCP per tenant.** Every customer gets an MCP endpoint, gated by API keys, that an LLM can hit for context without uploading the underlying documents. Token usage stays low.
- **A shared meta-MCP that learns across customers** *without* sharing customer data. As the system encounters new domains, it writes skills and markdown notes to itself describing how to organize *that kind* of information faster next time. The next customer in the same domain benefits from the structure; their content stays isolated.

## How the team works

This repository is built by a small team of AI agents coordinated by an Orchestrator (Claude). The Orchestrator reads `STATUS.md` and `BACKLOG.md` at the start of every session, decides what to do next, and spawns specialists in parallel where possible. There is no cron — work is mission-driven, not clock-driven.

See `AGENTS.md` for the team roster and `DECISIONS.md` for the running decision log. If you're an agent joining the team, read `AGENTS.md` first.

## For humans dropping in

- **Current state:** `STATUS.md`
- **What's next:** `BACKLOG.md`
- **Where we're headed:** `ROADMAP.md`
- **Why we made each call:** `DECISIONS.md`

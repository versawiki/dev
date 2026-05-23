---
name: Getting started
tags: [onboarding, getting-started, register, signup, first-steps]
last_reviewed: 2026-05-23
---

# Getting started with versawiki

Welcome. Three steps gets you a working private wiki for your documents.

## 1. Register a tenant

Sign up at `https://versawiki.app/signup` with your work email. You'll
receive a tenant slug (URL-safe identifier — e.g. `acme-eng`) and an
admin login. The tenant is your isolated workspace; nobody else can
read your data, including other versawiki customers.

If you'd prefer a self-hosted install, ask us — that's a paid option.

## 2. Issue an API key

From the admin UI, **Settings -> API keys -> Issue new key**. The raw
token (`vw_<prefix>_<secret>`) is shown **exactly once** — copy it
into your secret store now. We never store the raw secret, and lost
tokens cannot be recovered (you reissue and update your client).

API keys carry a `query` scope by default; an `admin`-scoped key is
issuable from the admin UI for orchestration use cases.

## 3. Point versawiki at a folder

Local folders work out of the box: install our CLI (`pip install
versawiki-cli`), run `versawiki connect ./my-docs`, and the ingestion
service starts indexing. Speed depends on file types and document
count — typical: ~5-15 documents/second after warmup.

Other connectors (Google Drive, OneDrive/SharePoint, Dropbox, Box,
iCloud) ship in M2 and later. We recommend starting with local for
the fastest feedback loop on classification + ontology quality.

## What happens next

Versawiki classifies each document, induces an ontology that fits
*your* corpus (no template forced on you), and serves both a wiki UI
and an MCP endpoint your LLM agents can hit. Recurring query
patterns reshape the index over time.

If anything is unclear, ask in this chat — we handle most onboarding
questions directly.

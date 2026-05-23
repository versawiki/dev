---
name: Ingestion
tags: [ingestion, indexing, sources, classifier, ontology, performance]
last_reviewed: 2026-05-23
---

# Ingestion

## What ingestion does

For each source you connect (local folder today; Drive/OneDrive/etc.
later), versawiki:

1. Walks the source, classifies each document (the type and the
   corpus shape it belongs to).
2. Chunks the document and embeds the chunks (1024-dim vectors in
   pgvector).
3. Inducts/refines an ontology specific to *your* corpus.
4. Pre-materialises wiki pages from clustered communities of related
   docs.
5. Listens to your queries and reshapes the index where they repeat.

## Expected speed

After warmup, around **5–15 documents per second** for typical mixes
of PDFs, Office docs, and plain text. Big corpora paginate; the first
useful pages typically appear in minutes, not hours.

OCR (scanned PDFs without text layers) is slower — count on ~1
doc/sec when OCR is involved.

## How to check status

- Admin UI → **Sources** lists every connected source with its state
  (`idle`, `running`, `paused`, `errored`).
- The support agent can run `lookup_ingestion_status(tenant_id,
  source_id)` for you and report state, last run time, and the count
  of files indexed.

## Common failure modes

| Symptom | Likely cause | What to try |
| --- | --- | --- |
| State stuck on `running`, no progress for >5 min | A very large file is being parsed or OCR'd | Wait; check the source page for the current file |
| State `errored` | A specific document failed; we capture the path | Check the error log on the source page; remove or fix the file |
| Auth error from a cloud connector | OAuth token expired | Re-authenticate from the connector settings |
| Some files missing | Excluded by a glob, or beyond per-plan limits | Check your source's include/exclude rules and plan limits |

## Pausing ingestion

You can pause a source at any time. Pausing is non-destructive — your
existing pages and embeddings remain available; new content just
stops flowing in. The support agent can pause a source for you.

## Resuming + re-indexing

Resuming picks up from the last successful checkpoint. Triggering a
full re-index from scratch is a destructive-ish action (it doesn't
delete data, but it rebuilds the embedding store); the agent will ask
for verification before doing it.

---
name: Troubleshooting
tags: [troubleshooting, errors, debug, auth, slow, stuck, fix]
last_reviewed: 2026-05-23
---

# Troubleshooting

## Auth errors (401 / 403)

Most common cause: a revoked or stale API key. Check:

- The `Authorization` header is exactly `Bearer vw_<prefix>_<secret>`
  (no `Token`, no quotes, no trailing whitespace).
- The key isn't revoked — list keys from the admin UI; revoked keys
  carry a `revoked_at` timestamp.
- The key has the scope you need. `query` works for read; admin
  endpoints require an `admin`-scoped key.

If you still see 401 with a valid-looking key, ask the agent to
reissue it (we'll do account verification first).

## Ingestion stuck on `running`

- Up to ~5 minutes is normal for large files (PDFs with OCR, big
  Office docs).
- Beyond that, ask the agent to `lookup_ingestion_status` — we'll
  tell you which file the worker is on and whether the worker is
  alive.
- If the worker has died and the source is genuinely stuck, the
  agent will pause the source so we can investigate without blocking
  you. Pausing is reversible.

## Slow queries

- Cold cache after a long quiet period: the second query is fast.
- Very broad queries ("all docs about X") are slower than narrow ones
  ("docs about X created last month").
- Embedding model swaps in M3 may change baselines; we'll annotate.

If query latency is consistently > 2s on a small tenant (<100k
docs), escalate — that's outside our spec and the team wants to know.

## "I can see fewer documents than I expected"

Check the source page for the `files_indexed` count vs. what's
actually on disk. Plan limits and your exclude rules are the two
common causes. The agent can read the count for you.

## Security incidents

If you suspect a key has leaked, or you see queries you didn't make:

1. Revoke the affected keys *now* from the admin UI.
2. Tell the agent the prefix you suspect (never the secret) — we
   will trace recent access on that key.
3. The agent escalates security incidents with **high severity** and
   a human picks up immediately.

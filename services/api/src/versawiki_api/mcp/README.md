# `versawiki_api.mcp`

Placeholder. The MCP-over-HTTP endpoint (BE-05 in `BACKLOG.md`) will
live here.

## What goes here

- `router.py` — `APIRouter` mounted at `/mcp` by
  `versawiki_api.routers.__init__.register_routers`.
- `transport.py` — streamable-HTTP transport adapter (the spec is
  evolving; pin the version we target at the top of this file).
- `tools/` — one module per MCP tool advertised to the LLM:
  - `search.py` — hybrid vector + keyword + ontology-filtered search.
  - `read_page.py` — pre-summarized wiki page fetch.
  - `read_chunk.py` — raw chunk fetch with citation.
  - `list_ontology.py` — ontology tree browse.
  - `recent_queries.py` — opt-in human-query feed.
- `descriptions.py` — per-tenant tool-description tuning hooked into
  the meta-MCP's learned skills.

## Cross-references

- `docs/architecture/v1.md` § 1.3 (tool list) and § 5 (transport, URL
  shape, token-budget discipline).
- `DECISIONS.md` 2026-05-22: "MCP transport = MCP-over-HTTP streamable".
- `BACKLOG.md` M1-BE-05.

## Why this placeholder exists

The skeleton must have the import path locked so BE-04 (query routes)
can share schemas with BE-05 (MCP tools) without circular imports. The
empty package + README pin the shape; BE-05 adds the modules.

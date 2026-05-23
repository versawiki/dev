"""Per-tenant MCP-over-HTTP endpoint (BE-05).

The package is split into:

- :mod:`.schemas` — Pydantic input/output models + JSON-Schema export
  for ``tools/list``.
- :mod:`.tools` — the four tool implementations (``search``,
  ``read_page``, ``read_chunk``, ``list_ontology``).
- :mod:`.transport` — JSON-RPC 2.0 dispatch + JSON / SSE response
  branching.
- :mod:`.router` — FastAPI ``APIRouter`` mounted by
  :func:`versawiki_api.routers.register_routers` at ``/mcp``.

Wire shape and reasoning live in ``docs/architecture/v1.md`` § 5.
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]

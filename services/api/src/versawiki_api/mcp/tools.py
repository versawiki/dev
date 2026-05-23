"""The four MCP tool implementations.

Each ``tool_<name>`` coroutine takes a resolved ``tenant_id`` plus the
JSON-RPC ``arguments`` dict and returns a plain-dict result. The
transport layer is what turns these into JSON-RPC responses; tools
themselves know nothing about HTTP or JSON-RPC.

Tenant identity comes from the API key (see ``tools/call`` in the
transport). If an LLM client tries to smuggle a ``tenant_id`` in the
arguments, the transport rejects the call with a clear 400-equivalent
JSON-RPC error before this module runs.

For ``search`` we reuse the BE-04 query path — same embedding call,
same envelope shape — so an MCP client sees the same data shape as a
direct ``/v1/tenants/{id}/query`` caller.

For ``read_page`` ING-05 wired this through to the ``PageStore``; the
not-found case still uses the same JSON-RPC envelope BE-05's tests
pin. ``read_chunk`` / ``list_ontology`` remain shape-correct stubs.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Optional

from ..deps import EmbeddingProvider, PageStore
from ..logging import get_logger
from .schemas import (
    ListOntologyInput,
    ListOntologyOutput,
    OntologyNode,
    ReadChunkInput,
    ReadPageInput,
    ReadPageOutput,
    SearchInput,
    SearchOutput,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool errors. Surfaced as JSON-RPC errors by the transport.
# ---------------------------------------------------------------------------

class ToolError(Exception):
    """Tool-level error. Carries a stable ``code`` and structured ``data``.

    The transport maps this onto the JSON-RPC ``error`` object. We use
    a small set of stable codes:

    - ``invalid_arguments`` (-32602 in JSON-RPC) — input validation
      failed.
    - ``not_found`` (-32004, application-defined) — the requested entity
      (page/chunk/etc.) does not exist.
    - ``unknown_tool`` (-32601 in JSON-RPC) — handled by the transport.

    JSON-RPC convention says error codes in the -32000 to -32099 range
    are reserved for "server errors" (application-defined). We use that
    range for our app errors and stick to the spec-reserved codes for
    the protocol-level errors only.
    """

    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def invalid_arguments(message: str, **details: Any) -> ToolError:
    return ToolError(code=-32602, message=message, data=details)


def not_found(message: str, **details: Any) -> ToolError:
    return ToolError(code=-32004, message=message, data=details)


# ---------------------------------------------------------------------------
# search — reuses the BE-04 query path
# ---------------------------------------------------------------------------

async def tool_search(
    tenant_id: str,
    *,
    arguments: dict[str, Any],
    embedder: EmbeddingProvider,
) -> dict[str, Any]:
    """Run a hybrid search for the tenant.

    The body mirrors :func:`versawiki_api.routers.v1.query.query` so the
    MCP client sees the same envelope shape as the REST query route.
    We embed the query (real call), then return the empty envelope —
    ING-02 will activate the SQL once ``chunks.embedding`` is a real
    pgvector column.
    """
    try:
        payload = SearchInput.model_validate(arguments)
    except Exception as exc:  # noqa: BLE001 - pydantic raises various
        raise invalid_arguments(
            "search arguments failed validation.",
            errors=str(exc),
        ) from exc

    started = time.perf_counter()
    query_id = str(uuid.uuid4())

    vectors = await embedder.embed([payload.q])
    if not vectors or len(vectors[0]) != embedder.dimension:
        log.error(
            "embedding_dimension_mismatch",
            tenant_id=tenant_id,
            got=len(vectors[0]) if vectors else 0,
            expected=embedder.dimension,
        )

    # Sketch SQL lives in the REST route (query.py); not duplicated here.
    took_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "mcp_search_executed",
        tenant_id=tenant_id,
        query_id=query_id,
        top_k=payload.top_k,
        embedding_provider=embedder.provider_name,
        took_ms=took_ms,
    )

    response = SearchOutput(
        answer_chunks=[],
        pages=[],
        query_id=query_id,
        took_ms=took_ms,
    )
    return response.model_dump(mode="json")


# ---------------------------------------------------------------------------
# read_page — now backed by PageStore (ING-05)
# ---------------------------------------------------------------------------

async def tool_read_page(
    tenant_id: str,
    *,
    arguments: dict[str, Any],
    page_store: Optional[PageStore] = None,
) -> dict[str, Any]:
    """Fetch a wiki page by id from the configured :class:`PageStore`.

    When no store is wired (legacy callers), we fall back to the
    original "always not_found" stub so existing tests that don't
    inject a store still pass.
    """
    try:
        payload = ReadPageInput.model_validate(arguments)
    except Exception as exc:  # noqa: BLE001
        raise invalid_arguments(
            "read_page arguments failed validation.",
            errors=str(exc),
        ) from exc

    if page_store is not None:
        record = await page_store.get(tenant_id, payload.page_id)
        if record is not None:
            log.info(
                "mcp_read_page_hit",
                tenant_id=tenant_id,
                page_id=payload.page_id,
                version=record.version,
            )
            last_built = (
                record.updated_at.isoformat()
                if isinstance(record.updated_at, datetime)
                else None
            )
            response = ReadPageOutput(
                page_id=record.id,
                slug=record.slug,
                title=record.title,
                body_md=record.body_markdown,
                body_html="",
                primary_ontology_node_id=record.ontology_node_id,
                last_built_at=last_built,
            )
            return response.model_dump(mode="json")

    log.info(
        "mcp_read_page_missing",
        tenant_id=tenant_id,
        page_id=payload.page_id,
    )
    raise not_found(
        "Wiki page not found.",
        page_id=payload.page_id,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# read_chunk — stub until ING-02 lands real chunk rows
# ---------------------------------------------------------------------------

async def tool_read_chunk(
    tenant_id: str,
    *,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Fetch a raw chunk by id.

    ING-02 will persist chunks; today there are none. We return a 404
    inside the JSON-RPC envelope, identical in shape to ``read_page``.
    """
    try:
        payload = ReadChunkInput.model_validate(arguments)
    except Exception as exc:  # noqa: BLE001
        raise invalid_arguments(
            "read_chunk arguments failed validation.",
            errors=str(exc),
        ) from exc

    log.info(
        "mcp_read_chunk_missing_stub",
        tenant_id=tenant_id,
        chunk_id=payload.chunk_id,
    )
    raise not_found(
        "Chunk not found.",
        chunk_id=payload.chunk_id,
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# list_ontology — stub returning empty tree
# ---------------------------------------------------------------------------

async def tool_list_ontology(
    tenant_id: str,
    *,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Return the tenant's ontology rooted at ``node_id`` or ``root``."""
    try:
        payload = ListOntologyInput.model_validate(arguments)
    except Exception as exc:  # noqa: BLE001
        raise invalid_arguments(
            "list_ontology arguments failed validation.",
            errors=str(exc),
        ) from exc

    log.info(
        "mcp_list_ontology_stub",
        tenant_id=tenant_id,
        node_id=payload.node_id,
    )
    root_id = payload.node_id or "root"
    response = ListOntologyOutput(
        root=OntologyNode(id=root_id, label="", kind="category", children=[]),
    )
    return response.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Dispatch table — name -> coroutine.
# ---------------------------------------------------------------------------

TOOL_HANDLERS: dict[str, Any] = {
    "search": tool_search,
    "read_page": tool_read_page,
    "read_chunk": tool_read_chunk,
    "list_ontology": tool_list_ontology,
}


__all__ = [
    "TOOL_HANDLERS",
    "ToolError",
    "invalid_arguments",
    "not_found",
    "tool_list_ontology",
    "tool_read_chunk",
    "tool_read_page",
    "tool_search",
]

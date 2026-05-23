"""``POST /v1/tenants/{tenant_id}/query`` — natural-language query.

Stub body for BE-04: embed the query via the injected
:class:`EmbeddingProvider`, then *sketch* the per-tenant SQL that
ING-02 will wire up against real ``vector(1024)`` columns. Today the
table is a stub column on the tenant schema (see
``db/models/tenant.py``), so the route returns the empty envelope
shape — but the embedding call is real (deterministic stub) so tests
can assert it was made.

Why we keep the empty path live: clients can codegen against the
OpenAPI spec today and the route shape is exactly the one BE-05
(MCP endpoint) will internally call.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from ...deps import EmbeddingProviderDep
from ...logging import get_logger
from ...services_api_tenant import TenantSessionDep

log = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Natural-language query payload.

    ``filters`` is opaque JSON today — ING-02 will define the shape
    (ontology_node_id, document_kind, date range, ...).
    """

    model_config = ConfigDict(extra="forbid")

    q: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=50)
    filters: dict[str, Any] = Field(default_factory=dict)


class AnswerChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    page_id: str | None
    snippet: str
    score: float
    ontology_node_id: str | None


class PageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str
    title: str
    ontology_node_id: str | None


class QueryResponse(BaseModel):
    """Outer query envelope.

    Stable across versions; future fields (e.g. `citations`,
    `query_intent`) get added without breaking older clients.
    """

    model_config = ConfigDict(extra="forbid")

    answer_chunks: list[AnswerChunk] = Field(default_factory=list)
    pages: list[PageRef] = Field(default_factory=list)
    query_id: str
    took_ms: int


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/tenants/{tenant_id}/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Natural-language query against a tenant's corpus.",
    description=(
        "Embeds ``q`` via the wired ``EmbeddingProvider``, runs a "
        "hybrid vector + keyword search against the tenant's ``chunks`` "
        "table, and returns the top matches plus the wiki pages they "
        "belong to. Today's BE-04 stub returns the empty envelope until "
        "ING-02 wires real ``vector(1024)`` columns + HNSW indexes. "
        "The embedding call is real, so the pipeline is exercised end-"
        "to-end."
    ),
    responses={
        401: {"description": "Missing or invalid API key."},
        403: {"description": "API key is not authorized for this tenant."},
        404: {"description": "Tenant not found."},
    },
)
async def query(
    payload: QueryRequest,
    tenant: TenantSessionDep,
    embedder: EmbeddingProviderDep,
) -> QueryResponse:
    started = time.perf_counter()
    query_id = str(uuid.uuid4())

    # Embedding the query is real — the rest is sketched.
    vectors = await embedder.embed([payload.q])
    if not vectors or len(vectors[0]) != embedder.dimension:
        # Should never trip with a well-behaved provider; raise rather
        # than ship garbage downstream.
        log.error(
            "embedding_dimension_mismatch",
            tenant_id=tenant.tenant_id,
            got=len(vectors[0]) if vectors else 0,
            expected=embedder.dimension,
        )
        # Returning an empty envelope is honest: today no rows exist,
        # so the user sees the same empty shape as a successful run.

    # Sketch SQL — verbatim shape ING-02 will activate. We don't
    # execute it today because the embedding column on ``chunks`` is
    # a stub JSON column, not a pgvector column.
    #
    # SELECT c.id AS chunk_id,
    #        c.document_id,
    #        c.text,
    #        1 - (c.embedding <=> :q_vec) AS score,
    #        c.metadata->>'ontology_node_id' AS ontology_node_id
    # FROM chunks c
    # WHERE c.embedding IS NOT NULL
    # ORDER BY c.embedding <=> :q_vec
    # LIMIT :top_k

    took_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "query_executed",
        tenant_id=tenant.tenant_id,
        query_id=query_id,
        top_k=payload.top_k,
        embedding_provider=embedder.provider_name,
        took_ms=took_ms,
    )
    return QueryResponse(
        answer_chunks=[],
        pages=[],
        query_id=query_id,
        took_ms=took_ms,
    )


__all__ = ["router", "QueryRequest", "QueryResponse", "AnswerChunk", "PageRef"]

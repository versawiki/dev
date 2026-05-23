"""`WikiPage` + `PageBuildJob` — the contracts for the page-builder layer.

`WikiPage` is the materialised view a reader sees. It's the same shape
the API's `GET /v1/tenants/{tid}/pages/{pid}` returns and the same
shape the MCP `read_page` tool emits. The fields are pinned because
they're part of the LLM-facing contract.

`PageBuildJob` is a tiny aggregate the pipeline uses internally to
carry "this node + its chunks + its classifier results" around
without leaking individual lists into method signatures.

Both are Pydantic v2 ``frozen=True`` — built once, then immutable so a
page handed to multiple readers can never drift mid-flight.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..classification.base import ClassifierResult
from ..ontology.models import OntologyNode
from ..pipeline.models import ChunkRecord


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class WikiPage(BaseModel):
    """One rendered wiki page.

    Identity is by ``id`` (server-issued, stable across rebuilds —
    every rebuild bumps ``version`` and ``updated_at`` but keeps the
    id). ``slug`` is a URL-friendly handle derived from the title;
    stable across rebuilds as long as the title doesn't change.

    ``body_markdown`` is the source the UI renders. ``summary`` is the
    short blurb the LLM writes (200-500 words target). ``chunk_ids``
    is the dedup list of `ChunkRecord.chunk_content_hash` values that
    fed this page — readers cite back to them via the search route.

    ``related_page_ids`` is filled by the pipeline (a single
    ``PageBuilder`` call can't know its siblings, so the field starts
    empty and the pipeline patches it in once all pages are built).

    Staleness is event-driven: ``is_stale`` flips to True when the
    ingestion-event bus reports a change underneath this page; the
    next reader triggers a background rebuild. ``version`` is the
    monotonic counter the rebuild increments.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    ontology_node_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    summary: str = Field(...)
    body_markdown: str = Field(...)
    chunk_ids: list[str] = Field(default_factory=list)
    related_page_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    is_stale: bool = Field(default=False)
    version: int = Field(default=1, ge=1)
    source_uri_count: int = Field(default=0, ge=0)
    predominant_doc_types: list[str] = Field(default_factory=list)

    def mark_stale(self) -> "WikiPage":
        """Return a copy with ``is_stale=True``. Frozen-model-safe."""
        return self.model_copy(update={"is_stale": True})

    def bump_version(self, **updates: Any) -> "WikiPage":
        """Return a rebuilt copy with ``version`` incremented + ``updated_at`` refreshed."""
        return self.model_copy(
            update={
                **updates,
                "version": self.version + 1,
                "updated_at": _utcnow(),
                "is_stale": False,
            }
        )


class PageBuildJob(BaseModel):
    """In-flight aggregate the builder + pipeline pass around.

    Bundles the inputs the page builder needs for one node:
      - the ontology node itself,
      - the chunks the inducer assigned to that node (already
        embedded; sorted is the builder's responsibility),
      - the classifier results indexed by document_content_hash so
        the builder can read the doc-type distribution without
        looking up every chunk's source document.

    Not persisted — purely an internal carrier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(..., min_length=1)
    node: OntologyNode
    chunks: list[ChunkRecord] = Field(default_factory=list)
    classifier_results: dict[str, ClassifierResult] = Field(default_factory=dict)


__all__ = ["PageBuildJob", "WikiPage"]

"""``PageStore`` Protocol + an in-memory impl, scoped to the API service.

The API does not import ``versawiki_ingestion`` at runtime (they are
sibling services per the v1 architecture; the ingestion service writes
to a Postgres table the API reads). To keep that boundary clean we
re-declare the minimum surface here — same shape as
``versawiki_ingestion.pages.PageStore``, just duck-typed.

``WikiPageRecord`` mirrors ``versawiki_ingestion.pages.models.WikiPage``
field-for-field. The ingestion side writes the canonical Pydantic
model into Postgres; the API reads back rows and reconstructs the
record. In tests we use ``InMemoryPageStore`` and the records are
constructed directly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class WikiPageRecord(BaseModel):
    """Server-side wiki page record.

    The same field set as the ingestion service's ``WikiPage``. We
    keep it Pydantic v2 ``frozen=True`` so it's safe to share across
    request scopes.
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


@runtime_checkable
class PageStore(Protocol):
    """Async store the API + MCP read paths use.

    Mirrors ``versawiki_ingestion.pages.PageStore`` shape. The
    in-process tests share `InMemoryPageStore`; production uses the
    Postgres impl (BE-04-followup).
    """

    async def upsert(self, page: WikiPageRecord) -> WikiPageRecord:
        ...

    async def get(
        self, tenant_id: str, page_id: str
    ) -> WikiPageRecord | None:
        ...

    async def get_by_slug(
        self, tenant_id: str, slug: str
    ) -> WikiPageRecord | None:
        ...

    async def list_for_node(
        self, tenant_id: str, ontology_node_id: str
    ) -> list[WikiPageRecord]:
        ...

    async def mark_stale(
        self, tenant_id: str, page_id: str
    ) -> WikiPageRecord | None:
        ...


class InMemoryPageStore:
    """Dict-backed store used in every API test.

    Identical behaviour to the ingestion service's
    ``InMemoryPageStore`` — duplicated here only to avoid the
    cross-service import.
    """

    def __init__(self) -> None:
        self._pages: dict[tuple[str, str], WikiPageRecord] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, page: WikiPageRecord) -> WikiPageRecord:
        async with self._lock:
            self._pages[(page.tenant_id, page.id)] = page
        return page

    async def get(
        self, tenant_id: str, page_id: str
    ) -> WikiPageRecord | None:
        return self._pages.get((tenant_id, page_id))

    async def get_by_slug(
        self, tenant_id: str, slug: str
    ) -> WikiPageRecord | None:
        for (tid, _pid), page in self._pages.items():
            if tid == tenant_id and page.slug == slug:
                return page
        return None

    async def list_for_node(
        self, tenant_id: str, ontology_node_id: str
    ) -> list[WikiPageRecord]:
        out = [
            p
            for (tid, _pid), p in self._pages.items()
            if tid == tenant_id and p.ontology_node_id == ontology_node_id
        ]
        out.sort(key=lambda p: (p.created_at, p.id))
        return out

    async def mark_stale(
        self, tenant_id: str, page_id: str
    ) -> WikiPageRecord | None:
        async with self._lock:
            existing = self._pages.get((tenant_id, page_id))
            if existing is None:
                return None
            if existing.is_stale:
                return existing
            stale = existing.model_copy(update={"is_stale": True})
            self._pages[(tenant_id, page_id)] = stale
            return stale


__all__ = [
    "InMemoryPageStore",
    "PageStore",
    "WikiPageRecord",
]

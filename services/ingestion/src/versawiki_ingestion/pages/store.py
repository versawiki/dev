"""`PageStore` Protocol + an in-memory impl + a Postgres impl signature.

The store is the persistence seam for ``WikiPage``. The page builder
calls ``upsert`` on the way out; the API + MCP read paths call
``get`` / ``get_by_slug`` / ``list_for_node`` on the way in;
``mark_stale`` is fired by the staleness hook when an upstream event
implies a page is now drifted.

Two impls ship in this ticket:

  - ``InMemoryPageStore`` — backs every test in both services.
    Thread-safe via ``asyncio.Lock`` so concurrent ``upsert`` calls
    don't corrupt the dict.
  - ``PostgresPageStore`` — signature-only stub. The real
    implementation will land in BE-04-followup once the
    ``pages`` table migration is in. The signature is pinned now so
    callers (api `deps.py`, future BE work) can typecheck against it.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from .models import WikiPage


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PageStore(Protocol):
    """Async store for ``WikiPage`` entities.

    Every method is tenant-scoped: the ``tenant_id`` parameter is
    enforced inside the store, mirroring the cross-tenant guard the
    API layer runs at the request edge. (Two layers of enforcement so
    a bug in either can't leak data.)
    """

    async def upsert(self, page: WikiPage) -> WikiPage:
        """Insert or update ``page``. Returns the canonical stored copy."""
        ...

    async def get(
        self, tenant_id: str, page_id: str
    ) -> WikiPage | None:
        """Return the page by id, or ``None``."""
        ...

    async def get_by_slug(
        self, tenant_id: str, slug: str
    ) -> WikiPage | None:
        """Return the page by slug, or ``None``."""
        ...

    async def list_for_node(
        self, tenant_id: str, ontology_node_id: str
    ) -> list[WikiPage]:
        """Return all pages for the given ontology node (usually 0 or 1)."""
        ...

    async def mark_stale(self, tenant_id: str, page_id: str) -> WikiPage | None:
        """Flip a page's ``is_stale`` to True. Returns the updated page or None."""
        ...


# ---------------------------------------------------------------------------
# InMemoryPageStore
# ---------------------------------------------------------------------------


class InMemoryPageStore:
    """Dict-backed store. Used in every test in both services.

    Storage shape: ``(tenant_id, page_id) -> WikiPage``.

    Concurrency: an ``asyncio.Lock`` serialises mutations. Reads are
    lock-free (dict access is atomic in CPython); they may briefly
    see an older snapshot, which is fine — the API layer doesn't
    promise read-after-write across concurrent upserts.
    """

    def __init__(self) -> None:
        self._pages: dict[tuple[str, str], WikiPage] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, page: WikiPage) -> WikiPage:
        key = (page.tenant_id, page.id)
        async with self._lock:
            self._pages[key] = page
        return page

    async def get(
        self, tenant_id: str, page_id: str
    ) -> WikiPage | None:
        return self._pages.get((tenant_id, page_id))

    async def get_by_slug(
        self, tenant_id: str, slug: str
    ) -> WikiPage | None:
        # Linear scan; this is the test impl. A real store hits an
        # index on (tenant_id, slug).
        for (tid, _pid), page in self._pages.items():
            if tid == tenant_id and page.slug == slug:
                return page
        return None

    async def list_for_node(
        self, tenant_id: str, ontology_node_id: str
    ) -> list[WikiPage]:
        out: list[WikiPage] = []
        for (tid, _pid), page in self._pages.items():
            if tid == tenant_id and page.ontology_node_id == ontology_node_id:
                out.append(page)
        # Deterministic order: by created_at ascending then id.
        out.sort(key=lambda p: (p.created_at, p.id))
        return out

    async def mark_stale(
        self, tenant_id: str, page_id: str
    ) -> WikiPage | None:
        key = (tenant_id, page_id)
        async with self._lock:
            existing = self._pages.get(key)
            if existing is None:
                return None
            if existing.is_stale:
                return existing
            stale = existing.mark_stale()
            self._pages[key] = stale
            return stale

    # ------------------------------------------------------------------
    # Test/debug helpers — not part of the Protocol.
    # ------------------------------------------------------------------

    async def all_pages(self) -> list[WikiPage]:
        return list(self._pages.values())

    def __len__(self) -> int:
        return len(self._pages)


# ---------------------------------------------------------------------------
# PostgresPageStore — signature only (real impl in BE-04-followup)
# ---------------------------------------------------------------------------


class PostgresPageStore:
    """Postgres-backed store. Real impl lands in BE-04-followup.

    The class exists today so:
      - `deps.py` can typecheck against it,
      - the migration ticket knows the exact method shape to
        implement,
      - integration tests can swap it in once the table is real.

    Every method raises ``NotImplementedError`` until then. The
    signatures match the ``PageStore`` Protocol verbatim — change one,
    change the other.
    """

    def __init__(self, session_factory) -> None:  # noqa: ANN001 - sqla session factory
        self._session_factory = session_factory

    async def upsert(self, page: WikiPage) -> WikiPage:
        raise NotImplementedError("PostgresPageStore: BE-04-followup")

    async def get(
        self, tenant_id: str, page_id: str
    ) -> WikiPage | None:
        raise NotImplementedError("PostgresPageStore: BE-04-followup")

    async def get_by_slug(
        self, tenant_id: str, slug: str
    ) -> WikiPage | None:
        raise NotImplementedError("PostgresPageStore: BE-04-followup")

    async def list_for_node(
        self, tenant_id: str, ontology_node_id: str
    ) -> list[WikiPage]:
        raise NotImplementedError("PostgresPageStore: BE-04-followup")

    async def mark_stale(
        self, tenant_id: str, page_id: str
    ) -> WikiPage | None:
        raise NotImplementedError("PostgresPageStore: BE-04-followup")


__all__ = [
    "InMemoryPageStore",
    "PageStore",
    "PostgresPageStore",
]

"""Stale-on-event materialisation hook.

DECISIONS.md commits to "stale-on-event" for page materialisation:
the page builder writes a fresh page on first ingest, the ingestion
event bus flips ``is_stale=True`` when something underneath the page
changes, and the next reader gets a background rebuild (the stale
page is served immediately so reads never block).

This module is the small, focused hook the event bus calls. It
inspects an event, decides which pages are affected, and returns the
mutated ``WikiPage`` instances. The store is responsible for
persisting them.

Three event flavours we care about, mirroring the meta-MCP event bus:

  - ``chunk_added`` — a new chunk landed; pages whose
    ``chunk_ids`` overlap with this chunk's ontology node go stale.
    Pages whose centroid would now shift also go stale (we
    over-approximate by marking *any* page on the node).
  - ``chunk_deleted`` — a chunk was removed; same rule.
  - ``ontology_re_induced`` — the ontology tree was rebuilt; every
    page on the affected tenant goes stale.

The decision logic is intentionally coarse — false-positive stale
flags are cheap (the rebuild is idempotent given the same inputs),
false-negative stale flags are dangerous (readers see drifted pages).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from .models import WikiPage

StalenessEventKind = Literal[
    "chunk_added",
    "chunk_deleted",
    "ontology_re_induced",
]


@dataclass(frozen=True)
class StalenessEvent:
    """An ingestion event that can flip pages stale.

    Carries just enough to identify which pages are affected:

      - ``tenant_id``: the owning tenant (events never cross tenants).
      - ``kind``: one of the literals above.
      - ``ontology_node_ids``: pages on these nodes go stale.
        Required for ``chunk_added`` / ``chunk_deleted`` events.
      - ``affects_all`` (default False): if True, every page in the
        tenant goes stale. Set by ``ontology_re_induced`` events.
    """

    tenant_id: str
    kind: StalenessEventKind
    ontology_node_ids: tuple[str, ...] = ()
    affects_all: bool = False

    @classmethod
    def for_chunk_added(
        cls, tenant_id: str, ontology_node_ids: Iterable[str]
    ) -> "StalenessEvent":
        return cls(
            tenant_id=tenant_id,
            kind="chunk_added",
            ontology_node_ids=tuple(ontology_node_ids),
        )

    @classmethod
    def for_chunk_deleted(
        cls, tenant_id: str, ontology_node_ids: Iterable[str]
    ) -> "StalenessEvent":
        return cls(
            tenant_id=tenant_id,
            kind="chunk_deleted",
            ontology_node_ids=tuple(ontology_node_ids),
        )

    @classmethod
    def for_ontology_re_induced(cls, tenant_id: str) -> "StalenessEvent":
        return cls(
            tenant_id=tenant_id,
            kind="ontology_re_induced",
            affects_all=True,
        )


def mark_stale_on_event(
    page: WikiPage,
    event: StalenessEvent,
) -> WikiPage:
    """Return a page (possibly stale) given an event.

    The function is pure: caller is responsible for persisting the
    result via the store. Returning a copy keeps the frozen-model
    semantics intact.
    """
    if page.tenant_id != event.tenant_id:
        # Cross-tenant events are ignored. The store API enforces
        # tenant scope; this is belt-and-braces.
        return page

    if page.is_stale:
        return page  # already stale; nothing to do.

    if event.affects_all:
        return page.mark_stale()

    if page.ontology_node_id in event.ontology_node_ids:
        return page.mark_stale()

    return page


__all__ = [
    "StalenessEvent",
    "StalenessEventKind",
    "mark_stale_on_event",
]

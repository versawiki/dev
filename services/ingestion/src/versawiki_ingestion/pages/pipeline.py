"""`PageBuildPipeline` — walks an ``OntologyTree`` and emits pages.

The pipeline is the layer above ``PageBuilder``. Inputs:

  - an ``OntologyTree`` (from `OntologyInducer.induce(...)`),
  - the flat list of every ``ChunkRecord`` for the tenant (the chunks
    the inducer saw; the pipeline indexes them by
    ``chunk_content_hash`` to find which chunks belong to each node),
  - the per-document ``ClassifierResult`` map.

For each node with at least ``min_chunks_for_page`` (default 2)
chunks, we build a page. Nodes with fewer chunks are *rolled up*: the
chunks are merged into the parent's chunk set, so the parent gets a
page that transitively covers the leaf's content. This matches the
ING-04 inducer's behaviour of leaving tiny clusters as leaves but
not materialising every one as a separate page.

After the per-node pages are built, we run a second pass to fill
``related_page_ids`` — that needs to be a single pass because
related-page resolution can't happen during the first walk (a node
doesn't know its sibling's page id until that sibling has been
built).

Persistence: every page is upserted into the injected ``PageStore``.
The returned list is in tree-walk order (roots first, then children),
deterministic given the same inputs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional, Sequence

from ..classification.base import ClassifierResult
from ..ontology.models import OntologyNode, OntologyTree
from ..pipeline.models import ChunkRecord
from .builder import (
    DEFAULT_MIN_CHUNKS_FOR_PAGE,
    PageBuilder,
    _stable_page_id,
)
from .models import WikiPage
from .store import PageStore


class PageBuildPipeline:
    """Walk an `OntologyTree` and materialise one page per qualifying node."""

    def __init__(
        self,
        *,
        builder: Optional[PageBuilder] = None,
        store: Optional[PageStore] = None,
        min_chunks_for_page: int = DEFAULT_MIN_CHUNKS_FOR_PAGE,
    ) -> None:
        self.builder: PageBuilder = builder or PageBuilder(
            min_chunks_for_page=min_chunks_for_page
        )
        self.store = store
        self.min_chunks_for_page = min_chunks_for_page

    # ------------------------------------------------------------------

    async def build_for_tree(
        self,
        tree: OntologyTree,
        all_chunks: Sequence[ChunkRecord],
        classifier_results: dict[str, ClassifierResult] | None = None,
        *,
        tenant_id: str,
    ) -> list[WikiPage]:
        """Build every page the tree justifies.

        Returns the list of pages in tree-walk order (roots first,
        then children, then grandchildren).
        """
        classifier_results = classifier_results or {}

        # 1. Index chunks by content hash for fast lookup.
        chunks_by_hash: dict[str, ChunkRecord] = {
            c.chunk_content_hash: c for c in all_chunks
        }

        # 2. Compute the effective chunk set per node, rolling tiny
        #    leaves up into their parents.
        effective: dict[str, list[ChunkRecord]] = self._compute_effective_chunks(
            tree, chunks_by_hash
        )

        # 3. Decide which nodes get pages (>= threshold chunks).
        nodes_for_pages: list[OntologyNode] = []
        for node in self._walk_tree(tree):
            if len(effective.get(node.id, [])) >= self.min_chunks_for_page:
                nodes_for_pages.append(node)

        # 4. Build the pages (first pass, no related_page_ids yet).
        pages: list[WikiPage] = []
        for node in nodes_for_pages:
            chunks = effective[node.id]
            page = await self.builder.build_for_node(
                node,
                chunks,
                classifier_results,
                tenant_id=tenant_id,
                tree=tree,
            )
            pages.append(page)

        # 5. Second pass: patch in related_page_ids from sibling /
        #    parent / child node ids. Each related-node id is mapped
        #    through `_stable_page_id` so we don't depend on the
        #    in-pass page list ordering.
        materialised_node_ids = {n.id for n in nodes_for_pages}
        finalised: list[WikiPage] = []
        for page in pages:
            related_ids = self._related_page_ids(
                tree=tree,
                node_id=page.ontology_node_id,
                tenant_id=tenant_id,
                materialised_node_ids=materialised_node_ids,
            )
            finalised.append(
                page.model_copy(update={"related_page_ids": related_ids})
            )

        # 6. Persist.
        if self.store is not None:
            for page in finalised:
                await self.store.upsert(page)

        return finalised

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _walk_tree(self, tree: OntologyTree) -> list[OntologyNode]:
        """Roots-first BFS walk for deterministic ordering."""
        out: list[OntologyNode] = []
        queue: list[OntologyNode] = list(tree.roots())
        while queue:
            node = queue.pop(0)
            out.append(node)
            queue.extend(tree.children_of(node.id))
        return out

    def _compute_effective_chunks(
        self,
        tree: OntologyTree,
        chunks_by_hash: dict[str, ChunkRecord],
    ) -> dict[str, list[ChunkRecord]]:
        """Return the chunks each node owns *after* rolling small leaves up.

        Strategy: start with each node's directly-assigned chunks. For
        each node that has fewer than ``min_chunks_for_page``, push its
        chunks into the nearest ancestor that *would* hit the threshold
        (or the root, if none do). This way, deep leaves with one chunk
        each still get reflected in the wiki — they just live in the
        parent's "Key documents" section instead of orphaning a tiny
        page.
        """
        direct: dict[str, list[ChunkRecord]] = defaultdict(list)
        for node_id, node in tree.nodes.items():
            for chash in node.chunk_ids:
                chunk = chunks_by_hash.get(chash)
                if chunk is not None:
                    direct[node_id].append(chunk)

        effective: dict[str, list[ChunkRecord]] = {
            nid: list(chunks) for nid, chunks in direct.items()
        }
        # Ensure every node has an entry (even if empty) so subsequent
        # lookups are cheap.
        for nid in tree.nodes:
            effective.setdefault(nid, [])

        # Walk leaves-up: for each node with too few direct chunks,
        # push its chunks to the parent (which may also be small; the
        # walk will roll it up further).
        # We sort nodes by depth descending so the deepest are
        # processed first.
        depth_of = self._depth_map(tree)
        nodes_by_depth = sorted(
            tree.nodes.values(),
            key=lambda n: depth_of[n.id],
            reverse=True,
        )
        for node in nodes_by_depth:
            if node.parent_id is None:
                continue
            if len(effective[node.id]) >= self.min_chunks_for_page:
                continue
            # Push into parent.
            effective[node.parent_id].extend(effective[node.id])

        return effective

    def _depth_map(self, tree: OntologyTree) -> dict[str, int]:
        """Per-node depth from root. Used to roll leaves up before parents."""
        depth: dict[str, int] = {}

        def _depth_of(nid: str) -> int:
            if nid in depth:
                return depth[nid]
            node = tree.nodes[nid]
            if node.parent_id is None:
                depth[nid] = 0
            else:
                depth[nid] = 1 + _depth_of(node.parent_id)
            return depth[nid]

        for nid in tree.nodes:
            _depth_of(nid)
        return depth

    def _related_page_ids(
        self,
        *,
        tree: OntologyTree,
        node_id: str,
        tenant_id: str,
        materialised_node_ids: set[str],
    ) -> list[str]:
        """Compute related_page_ids for one page.

        Includes parent, siblings (same parent, not self), and children
        — but only those whose nodes actually got materialised as
        pages (otherwise the related-link is a dead reference). The
        result is cycle-free by construction: we never include the
        node itself.
        """
        node = tree.nodes[node_id]
        related: list[str] = []
        seen: set[str] = set()

        def _add(other_id: str) -> None:
            if other_id == node_id:
                return
            if other_id not in materialised_node_ids:
                return
            page_id = _stable_page_id(tenant_id, other_id)
            if page_id in seen:
                return
            seen.add(page_id)
            related.append(page_id)

        # Parent.
        if node.parent_id is not None:
            _add(node.parent_id)
        # Siblings.
        if node.parent_id is not None:
            for sib in tree.children_of(node.parent_id):
                _add(sib.id)
        # Children.
        for kid in tree.children_of(node.id):
            _add(kid.id)
        return related


__all__ = ["PageBuildPipeline"]

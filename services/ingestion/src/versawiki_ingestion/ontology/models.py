"""`OntologyNode` + `OntologyTree` — the in-memory shape of an induced ontology.

These mirror the `ontology_nodes` table in `docs/architecture/v1.md` §2:

  ontology_nodes(id, parent_id, label, kind, embedding vector(1024),
                 confidence, source)

We collapse the architectural ``source`` and ``kind`` columns into one
``kind: Literal["seed", "induced"]`` here because that's the only distinction
the inducer cares about. The richer Postgres-level ``kind``
(`category | entity | topic`) is a persistence concern BE-03 layers on.

Both models are Pydantic v2 ``frozen=True`` so a tree, once built, can be
hashed, diffed against a previous version, and shared between threads
without defensive copies.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..embedding.base import EMBEDDING_DIM

NodeKind = Literal["seed", "induced"]


class OntologyNode(BaseModel):
    """One node in the tenant's induced ontology tree.

    Identity is by ``id`` — a stable string the inducer assigns once and
    preserves across re-induction runs whenever the label survives
    (see `merge.merge_with_existing`).

    ``parent_id`` is ``None`` for roots. ``chunk_ids`` is the set of chunk
    content hashes the inducer assigned to this node *directly* (not the
    transitive closure over descendants — callers walk the tree if they
    want totals).

    ``centroid_embedding`` is the mean of the chunk embeddings under this
    node when the node was built. It's stored at full ``EMBEDDING_DIM`` so
    downstream code can index it the same way as chunk embeddings.

    ``confidence`` is the inducer's [0,1] estimate of how well the cluster
    that produced this node hangs together. Seed nodes always get
    ``confidence=1.0``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(..., min_length=1)
    parent_id: Optional[str] = Field(default=None)
    label: str = Field(..., min_length=1)
    kind: NodeKind = Field(...)
    chunk_ids: list[str] = Field(default_factory=list)
    centroid_embedding: list[float] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_embedding_dimension(self) -> "OntologyNode":
        # Allow empty centroid (a node that hasn't been embedded yet, or a
        # pure seed root before any chunk lands) but if present it must be
        # the locked dimension.
        if self.centroid_embedding and len(self.centroid_embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"OntologyNode.centroid_embedding has dim="
                f"{len(self.centroid_embedding)}; expected {EMBEDDING_DIM}"
            )
        return self


class OntologyTree(BaseModel):
    """Aggregate over a set of nodes that share a common root structure.

    The tree is not a linked structure — it's a flat dict keyed by node id,
    with each node carrying its own ``parent_id``. That makes it cheap to
    serialise, diff, and persist row-by-row.

    Invariants enforced at construction:

      * Every ``parent_id`` either references another node in the same tree
        or is ``None``.
      * No cycles (a node can't be its own ancestor).
      * No duplicate ids.

    A tree with zero nodes is allowed (empty corpus, empty tree).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: dict[str, OntologyNode] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_structure(self) -> "OntologyTree":
        ids = set(self.nodes.keys())
        for nid, node in self.nodes.items():
            if node.id != nid:
                raise ValueError(
                    f"OntologyTree key {nid!r} != node.id {node.id!r}"
                )
            if node.parent_id is not None and node.parent_id not in ids:
                raise ValueError(
                    f"OntologyNode {nid!r} has parent_id "
                    f"{node.parent_id!r} which is not in the tree"
                )
        # Cycle check: walk each node up to a root and bail if we revisit.
        for nid in self.nodes:
            seen: set[str] = set()
            cur: Optional[str] = nid
            while cur is not None:
                if cur in seen:
                    raise ValueError(
                        f"OntologyTree contains a cycle through node {nid!r}"
                    )
                seen.add(cur)
                cur = self.nodes[cur].parent_id
        return self

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def roots(self) -> list[OntologyNode]:
        """Return nodes with no parent, in insertion order."""
        return [n for n in self.nodes.values() if n.parent_id is None]

    def children_of(self, node_id: str) -> list[OntologyNode]:
        """Direct children of ``node_id`` (not the transitive closure)."""
        return [n for n in self.nodes.values() if n.parent_id == node_id]

    def depth(self) -> int:
        """Max root-to-leaf depth. A tree with one root only is depth 1."""
        if not self.nodes:
            return 0

        def _below(nid: str) -> int:
            kids = self.children_of(nid)
            if not kids:
                return 1
            return 1 + max(_below(k.id) for k in kids)

        return max((_below(r.id) for r in self.roots()), default=0)

    def leaves(self) -> list[OntologyNode]:
        """Nodes with no children."""
        with_kids = {
            n.parent_id for n in self.nodes.values() if n.parent_id is not None
        }
        return [n for n in self.nodes.values() if n.id not in with_kids]

    def all_chunk_ids(self) -> list[str]:
        """Flat list of every chunk id referenced anywhere in the tree."""
        out: list[str] = []
        for node in self.nodes.values():
            out.extend(node.chunk_ids)
        return out

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, node_id: object) -> bool:
        return isinstance(node_id, str) and node_id in self.nodes

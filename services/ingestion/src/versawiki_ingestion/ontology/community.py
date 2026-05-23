"""Community detection on the chunk-similarity graph.

The locked recipe is Leiden over a graph where nodes are clusters and edges
are the cosine similarity between their centroid embeddings (above a
threshold). Leiden requires `python-igraph` and `leidenalg`, neither of
which is reliably installable in the sandbox.

So this module ships:

  * `OntologyCommunityDetector` — Protocol both implementations satisfy.
  * `SimpleConnectedComponentsDetector` — numpy-only fallback used in
    tests and the sandbox. Builds the same threshold graph and returns
    its connected components.
  * `LeidenCommunityDetector` — the real implementation, lazy-imports
    `igraph` + `leidenalg`. Gated tests use `pytest.mark.skipif(...)`.

Both detectors produce a `CommunityDetectionResult` keyed by community id
with the cluster ids in each community. The inducer uses these to group
clusters into parent nodes (depth-2 from a root) — a community becomes a
"category" and its member clusters become "topics" under it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from ..embedding.base import EMBEDDING_DIM


# ----------------------------------------------------------------------
# Data shapes
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Community:
    """One community in the cluster graph.

    ``community_id`` is a stable integer id (0-indexed by insertion order
    in the result). ``cluster_ids`` is the set of cluster ids that belong
    to the community.
    """

    community_id: int
    cluster_ids: list[int]


@dataclass(frozen=True)
class CommunityDetectionResult:
    """Output of a community-detection pass."""

    communities: list[Community]

    @property
    def num_communities(self) -> int:
        return len(self.communities)

    def community_for_cluster(self, cluster_id: int) -> Optional[int]:
        for c in self.communities:
            if cluster_id in c.cluster_ids:
                return c.community_id
        return None


# ----------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------


@runtime_checkable
class OntologyCommunityDetector(Protocol):
    """Detect communities over a list of cluster centroids."""

    name: str

    def detect(self, centroids: Sequence[Sequence[float]]) -> CommunityDetectionResult: ...


# ----------------------------------------------------------------------
# SimpleConnectedComponentsDetector — numpy-only fallback.
# ----------------------------------------------------------------------


class SimpleConnectedComponentsDetector:
    """Threshold the cluster-similarity matrix and return connected components.

    Build a sparse undirected graph: cluster i is connected to cluster j
    iff ``cosine(centroid_i, centroid_j) >= threshold``. Then return the
    connected components of that graph as communities.

    With a high threshold (default 0.85), unrelated clusters end up in
    their own singleton communities — which is exactly what we want for
    the AEC seed taxonomy bootstrap where each seed type is structurally
    distinct.
    """

    name = "connected-components"

    def __init__(self, *, similarity_threshold: float = 0.85) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be in [0,1]")
        self.similarity_threshold = similarity_threshold

    def detect(
        self, centroids: Sequence[Sequence[float]]
    ) -> CommunityDetectionResult:
        if not centroids:
            return CommunityDetectionResult(communities=[])

        n = len(centroids)
        # Validate dimension consistency without forcing a numpy import for
        # the trivial single-cluster case.
        for c in centroids:
            if len(c) != EMBEDDING_DIM and len(c) != len(centroids[0]):
                raise ValueError(
                    f"centroid dim mismatch: got {len(c)}, expected "
                    f"{len(centroids[0])} (or {EMBEDDING_DIM})"
                )

        # Adjacency as a dict-of-sets, union-find for components.
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        thr = self.similarity_threshold
        for i in range(n):
            for j in range(i + 1, n):
                sim = _cosine(centroids[i], centroids[j])
                if sim >= thr:
                    union(i, j)

        # Group by component root, in deterministic order.
        comps: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            comps.setdefault(root, []).append(i)
        # Stable community ids: order by the smallest cluster id in each.
        ordered = sorted(comps.values(), key=lambda lst: lst[0])
        communities = [
            Community(community_id=i, cluster_ids=lst)
            for i, lst in enumerate(ordered)
        ]
        return CommunityDetectionResult(communities=communities)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity. Returns 0.0 on a zero vector to avoid NaN."""
    if len(a) != len(b):
        raise ValueError(f"cosine: length mismatch {len(a)} vs {len(b)}")
    num = 0.0
    aa = 0.0
    bb = 0.0
    for x, y in zip(a, b):
        num += x * y
        aa += x * x
        bb += y * y
    if aa <= 0.0 or bb <= 0.0:
        return 0.0
    return num / math.sqrt(aa * bb)


# ----------------------------------------------------------------------
# LeidenCommunityDetector — placeholder for the real impl.
# ----------------------------------------------------------------------


class LeidenCommunityDetector:
    """Adapter around `python-igraph` + `leidenalg`. Lazy-imports both."""

    name = "leiden"

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.85,
        resolution: float = 1.0,
        seed: int = 0,
    ) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be in [0,1]")
        self.similarity_threshold = similarity_threshold
        self.resolution = resolution
        self.seed = seed

    def detect(
        self, centroids: Sequence[Sequence[float]]
    ) -> CommunityDetectionResult:
        try:
            import igraph as ig  # type: ignore[import-not-found]
            import leidenalg  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover — environment-dependent
            raise RuntimeError(
                "LeidenCommunityDetector requires 'python-igraph' and "
                "'leidenalg'; install both or use "
                "SimpleConnectedComponentsDetector for sandboxed runs."
            ) from e

        if not centroids:
            return CommunityDetectionResult(communities=[])

        n = len(centroids)
        edges: list[tuple[int, int]] = []
        weights: list[float] = []
        for i in range(n):
            for j in range(i + 1, n):
                sim = _cosine(centroids[i], centroids[j])
                if sim >= self.similarity_threshold:
                    edges.append((i, j))
                    weights.append(sim)

        g = ig.Graph(n=n, edges=edges, directed=False)
        if weights:
            g.es["weight"] = weights
        partition = leidenalg.find_partition(
            g,
            leidenalg.RBConfigurationVertexPartition,
            weights=weights or None,
            resolution_parameter=self.resolution,
            seed=self.seed,
        )

        membership = list(partition.membership)
        groups: dict[int, list[int]] = {}
        for vertex, comm in enumerate(membership):
            groups.setdefault(int(comm), []).append(vertex)
        ordered = sorted(groups.values(), key=lambda lst: lst[0])
        communities = [
            Community(community_id=i, cluster_ids=lst)
            for i, lst in enumerate(ordered)
        ]
        return CommunityDetectionResult(communities=communities)

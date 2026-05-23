"""Chunk clustering for ontology induction.

The locked recipe (per `docs/research/ontology.md` §2 + `DECISIONS.md`
2026-05-22) is **BERTopic** — UMAP -> HDBSCAN -> c-TF-IDF labels. BERTopic
pulls in `umap-learn`, `hdbscan`, `sklearn`, `scipy`, `numba`, and several
hundred MB of dependencies; we cannot reasonably install that in the test
sandbox.

So this module ships:

  * `OntologyClusterer` — the Protocol both implementations satisfy.
  * `SimpleEmbeddingClusterer` — a numpy-only k-means clusterer used as
    the active implementation in the sandbox and in CI. Same Protocol,
    deterministic given a seed.
  * `BERTopicClusterer` — a thin wrapper around the real BERTopic that
    *imports lazily*. It raises a clear ``RuntimeError`` if BERTopic isn't
    installed. Tests for it live behind a ``skipif`` guard.

Swapping in BERTopic in production is a config flag — the rest of the
ontology pipeline never touches the concrete type, only the Protocol.
See `notes/ingestion.md` for the swap procedure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from ..embedding.base import EMBEDDING_DIM
from ..pipeline.models import ChunkRecord


# ----------------------------------------------------------------------
# Data shapes
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkClusterAssignment:
    """Which cluster a single chunk landed in."""

    chunk_content_hash: str
    cluster_id: int  # -1 means "noise / unassigned" (BERTopic convention).


@dataclass(frozen=True)
class ClusterResult:
    """Output of a clustering pass over a chunk corpus.

    ``cluster_centroids[i]`` is the centroid of cluster ``i`` (a list of
    ``EMBEDDING_DIM`` floats). ``noise_chunks`` lists the chunk hashes
    HDBSCAN-style clusterers couldn't assign — empty for k-means-like
    implementations that force every chunk into a cluster.
    """

    assignments: list[ChunkClusterAssignment]
    cluster_centroids: list[list[float]]
    noise_chunks: list[str]

    @property
    def num_clusters(self) -> int:
        return len(self.cluster_centroids)


# ----------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------


@runtime_checkable
class OntologyClusterer(Protocol):
    """Cluster a list of embedded `ChunkRecord` instances.

    Implementations MAY drop chunks without embeddings (degraded fallback)
    but SHOULD treat that as an upstream bug and surface it in logs.
    """

    name: str

    def cluster(self, chunks: Sequence[ChunkRecord]) -> ClusterResult: ...


# ----------------------------------------------------------------------
# SimpleEmbeddingClusterer — numpy-only fallback (active in the sandbox).
# ----------------------------------------------------------------------


class SimpleEmbeddingClusterer:
    """Deterministic numpy k-means over embedded chunks.

    Strategy: pick ``k`` initial centroids via k-means++ style farthest-point
    seeding (deterministic given ``seed``), then run Lloyd's algorithm
    until centroids stop moving or ``max_iter`` is exhausted.

    ``k`` is chosen as ``min(target_clusters, max(2, sqrt(n/2)))`` when not
    pinned by the caller. We never produce more clusters than there are
    chunks; we never produce fewer than 2 unless the corpus has fewer than
    2 chunks (degenerate case).

    The output uses cluster IDs ``0..k-1``; we never emit ``-1`` for noise
    because k-means assigns every point. Downstream code that conditions
    on ``noise_chunks`` will simply see an empty list.
    """

    name = "simple-kmeans"

    def __init__(
        self,
        *,
        target_clusters: Optional[int] = None,
        max_iter: int = 50,
        seed: int = 0,
        tol: float = 1e-4,
    ) -> None:
        if target_clusters is not None and target_clusters < 1:
            raise ValueError("target_clusters must be >= 1 when provided")
        if max_iter < 1:
            raise ValueError("max_iter must be >= 1")
        self.target_clusters = target_clusters
        self.max_iter = max_iter
        self.seed = seed
        self.tol = tol

    def cluster(self, chunks: Sequence[ChunkRecord]) -> ClusterResult:
        import numpy as np

        embedded = [c for c in chunks if c.embedding is not None]
        if not embedded:
            return ClusterResult(
                assignments=[], cluster_centroids=[], noise_chunks=[]
            )

        # Stack embeddings as a (n, dim) float64 array. Numpy is the only
        # heavy dep we permit; the ingestion package already implies it
        # via openpyxl and friends.
        X = np.asarray(
            [list(c.embedding or []) for c in embedded], dtype=np.float64
        )
        n, dim = X.shape
        if dim != EMBEDDING_DIM:
            raise ValueError(
                f"SimpleEmbeddingClusterer got dim={dim}; expected {EMBEDDING_DIM}"
            )

        k = self._pick_k(n)
        if k >= n:
            # Trivial: every chunk is its own cluster.
            return ClusterResult(
                assignments=[
                    ChunkClusterAssignment(c.chunk_content_hash, i)
                    for i, c in enumerate(embedded)
                ],
                cluster_centroids=[list(X[i]) for i in range(n)],
                noise_chunks=[],
            )

        centroids = self._seed_centroids(X, k)
        labels = np.zeros(n, dtype=np.int64)

        for _ in range(self.max_iter):
            # Assignment step: nearest centroid (squared-euclidean).
            dists = self._sqdist(X, centroids)
            new_labels = np.argmin(dists, axis=1)
            # Update step: mean per cluster; empty clusters keep their old
            # centroid (rare but possible with extreme seeds).
            new_centroids = centroids.copy()
            for ci in range(k):
                mask = new_labels == ci
                if mask.any():
                    new_centroids[ci] = X[mask].mean(axis=0)
            shift = float(np.linalg.norm(new_centroids - centroids))
            centroids = new_centroids
            labels = new_labels
            if shift < self.tol:
                break

        assignments = [
            ChunkClusterAssignment(c.chunk_content_hash, int(labels[i]))
            for i, c in enumerate(embedded)
        ]
        cluster_centroids = [centroids[i].tolist() for i in range(k)]
        return ClusterResult(
            assignments=assignments,
            cluster_centroids=cluster_centroids,
            noise_chunks=[],
        )

    # ------------------------------------------------------------------

    def _pick_k(self, n: int) -> int:
        if n <= 1:
            return 1
        if self.target_clusters is not None:
            return min(self.target_clusters, n)
        # Heuristic: sqrt(n/2), at least 2, at most n.
        proposed = max(2, int(math.sqrt(max(1, n / 2))))
        return min(proposed, n)

    def _seed_centroids(self, X: Any, k: int) -> Any:
        """k-means++ flavoured deterministic seeding."""
        import numpy as np

        n = X.shape[0]
        # Use a numpy RNG keyed to self.seed for determinism.
        rng = np.random.default_rng(self.seed)
        # First centroid: row 0 (deterministic). Then farthest-point each step.
        idx0 = 0 if n > 0 else 0
        chosen = [idx0]
        for _ in range(1, k):
            d2 = self._sqdist(X, X[np.array(chosen)])
            # Distance to nearest already-chosen centroid for each point.
            min_d2 = d2.min(axis=1)
            # Avoid picking the same point twice: zero-out chosen indices.
            for c in chosen:
                min_d2[c] = -1.0
            # Weighted choice on positive distances; if all zero pick max-d2.
            total = float(min_d2[min_d2 > 0].sum())
            if total <= 0.0:
                # Fall back to the row with largest distance (still deterministic).
                nxt = int(np.argmax(min_d2))
            else:
                probs = np.where(min_d2 > 0, min_d2 / total, 0.0)
                nxt = int(rng.choice(n, p=probs))
            chosen.append(nxt)
        return X[np.array(chosen)].copy()

    @staticmethod
    def _sqdist(A: Any, B: Any) -> Any:
        """Pairwise squared Euclidean distance, broadcast-style."""
        import numpy as np

        # Use the ||a-b||^2 = ||a||^2 + ||b||^2 - 2 a.b trick — same result,
        # cheaper than full broadcasting at our scales.
        aa = (A * A).sum(axis=1, keepdims=True)
        bb = (B * B).sum(axis=1, keepdims=True).T
        ab = A @ B.T
        return np.clip(aa + bb - 2.0 * ab, 0.0, None)


# ----------------------------------------------------------------------
# BERTopicClusterer — placeholder for the real impl, gated on import.
# ----------------------------------------------------------------------


class BERTopicClusterer:
    """Adapter around the real BERTopic library.

    Lazily imports ``bertopic`` on first ``cluster()`` call. Raises a clear
    error if not installed so the caller can either install it or swap in
    `SimpleEmbeddingClusterer`. Tests that exercise this path use a
    ``pytest.mark.skipif(...)`` guard on the import.
    """

    name = "bertopic"

    def __init__(
        self,
        *,
        min_topic_size: int = 5,
        nr_topics: Optional[int] = None,
        random_state: int = 0,
    ) -> None:
        self.min_topic_size = min_topic_size
        self.nr_topics = nr_topics
        self.random_state = random_state

    def cluster(self, chunks: Sequence[ChunkRecord]) -> ClusterResult:
        try:
            from bertopic import BERTopic  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover — environment-dependent
            raise RuntimeError(
                "BERTopicClusterer requires the 'bertopic' package; install it or "
                "use SimpleEmbeddingClusterer for sandboxed / CI runs."
            ) from e

        import numpy as np  # pragma: no cover — only on the BERTopic path

        embedded = [c for c in chunks if c.embedding is not None]
        if not embedded:
            return ClusterResult(
                assignments=[], cluster_centroids=[], noise_chunks=[]
            )

        texts = [c.text for c in embedded]
        embeddings = np.asarray(
            [list(c.embedding or []) for c in embedded], dtype=np.float64
        )
        model = BERTopic(
            min_topic_size=self.min_topic_size,
            nr_topics=self.nr_topics,
            calculate_probabilities=False,
            verbose=False,
        )
        topics, _ = model.fit_transform(texts, embeddings)

        # BERTopic uses -1 for outliers; pass that through as noise.
        assignments: list[ChunkClusterAssignment] = []
        noise: list[str] = []
        for chunk, topic_id in zip(embedded, topics):
            tid = int(topic_id)
            assignments.append(ChunkClusterAssignment(chunk.chunk_content_hash, tid))
            if tid == -1:
                noise.append(chunk.chunk_content_hash)

        # Build centroids from BERTopic topic_embeddings_ if present.
        try:
            topic_embeds = model.topic_embeddings_
        except AttributeError:
            topic_embeds = None

        if topic_embeds is not None:
            centroids = [list(map(float, v)) for v in np.asarray(topic_embeds)]
        else:
            # Fall back to mean-per-cluster from input embeddings.
            unique_topics = sorted({int(t) for t in topics if int(t) != -1})
            centroids = []
            for tid in unique_topics:
                mask = np.array([int(t) == tid for t in topics])
                centroids.append(embeddings[mask].mean(axis=0).tolist())

        return ClusterResult(
            assignments=assignments,
            cluster_centroids=centroids,
            noise_chunks=noise,
        )

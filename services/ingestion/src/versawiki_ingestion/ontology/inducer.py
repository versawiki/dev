"""`OntologyInducer` — orchestrates clustering, labelling, community detection.

The pipeline (matching `docs/research/ontology.md` §M1 recommendation):

  1. **Cluster** the embedded chunks. The clusterer Protocol abstracts
     BERTopic-vs-SimpleEmbeddingClusterer; the inducer doesn't care which.
  2. **Propose labels** for each cluster via the LLM taxonomy proposer.
  3. **Detect communities** over the cluster centroids — same protocol
     trick for Leiden-vs-connected-components.
  4. **Bootstrap roots**: if the corpus matches the AEC seed taxonomy
     (heuristic — see ``_corpus_looks_aec_shaped``), the tree's roots are
     seeded from `aec_starter_taxonomy.yaml` and induced clusters attach
     under the best-matching seed root. Otherwise the LLM-proposed roots
     stand on their own.
  5. **Assemble** an `OntologyTree`: root nodes (seed or proposed) ->
     community nodes (induced "category") -> cluster nodes (induced
     "topic" with attached chunk_ids).

The result is the in-memory shape the BE-03 persistence layer ingests.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from ..classification.taxonomy import Taxonomy
from ..embedding.base import EMBEDDING_DIM
from ..pipeline.models import ChunkRecord
from .clusterer import (
    ClusterResult,
    OntologyClusterer,
    SimpleEmbeddingClusterer,
)
from .community import (
    CommunityDetectionResult,
    OntologyCommunityDetector,
    SimpleConnectedComponentsDetector,
    _cosine,
)
from .models import OntologyNode, OntologyTree
from .taxonomy_proposer import (
    LLMTaxonomyProposer,
    ProposedLabel,
    StubTaxonomyProposer,
)


# ----------------------------------------------------------------------
# AEC corpus-shape heuristic
# ----------------------------------------------------------------------


# Tokens that, if they appear together in the corpus's most-common terms,
# suggest the corpus is AEC-shaped and seed bootstrapping makes sense.
# Mirrors the seed taxonomy types in aec_starter_taxonomy.yaml.
_AEC_SIGNAL_TOKENS = frozenset(
    {
        "rfi", "submittal", "spec", "specification", "contract", "drawing",
        "transmittal", "engineering", "construction", "calculation",
        "design", "discipline", "civil", "structural", "mechanical",
        "electrical", "subcontract", "amendment",
    }
)

_AEC_THRESHOLD = 3  # Need at least this many distinct AEC signals.

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _corpus_looks_aec_shaped(chunks: Sequence[ChunkRecord]) -> bool:
    """Coarse keyword sniff over the corpus to decide the bootstrap path.

    We don't need to be precise here — false positive seeds the AEC roots
    (which is harmless; the tree still works), false negative skips the
    seed and uses LLM-proposed roots only.
    """
    hits: set[str] = set()
    for chunk in chunks:
        text = chunk.text.lower()
        for tok in _WORD_RE.findall(text):
            if tok in _AEC_SIGNAL_TOKENS:
                hits.add(tok)
                if len(hits) >= _AEC_THRESHOLD:
                    return True
    return False


# ----------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------


@dataclass
class OntologyInducer:
    """Top-level induction orchestrator.

    All fields are dataclass-default-constructible to the in-sandbox
    fallback chain (Simple clusterer + Stub proposer + ConnectedComponents
    detector). Production wiring swaps these out via constructor args.
    """

    clusterer: OntologyClusterer = field(default_factory=SimpleEmbeddingClusterer)
    proposer: LLMTaxonomyProposer = field(default_factory=StubTaxonomyProposer)
    community_detector: OntologyCommunityDetector = field(
        default_factory=SimpleConnectedComponentsDetector
    )
    seed_taxonomy: Optional[Taxonomy] = None

    async def induce(self, chunks: Sequence[ChunkRecord]) -> OntologyTree:
        """Run the full pipeline and return the induced tree."""
        # 1. Cluster.
        cluster_result = self.clusterer.cluster(chunks)
        if not cluster_result.cluster_centroids:
            return OntologyTree(nodes={})

        # 2. Propose labels.
        proposals = await self.proposer.propose(cluster_result, chunks)
        # Build a quick cluster_id -> ProposedLabel map; fall back to a
        # numbered label for any missing cluster.
        labels_by_cluster: dict[int, ProposedLabel] = {
            p.cluster_id: p for p in proposals
        }
        for ci in range(cluster_result.num_clusters):
            labels_by_cluster.setdefault(
                ci, ProposedLabel(cluster_id=ci, label=f"cluster_{ci}", confidence=0.5)
            )

        # 3. Detect communities.
        communities = self.community_detector.detect(cluster_result.cluster_centroids)

        # 4. Decide whether to bootstrap from AEC seeds.
        use_seed_roots = (
            self.seed_taxonomy is not None
            and _corpus_looks_aec_shaped(chunks)
        )

        # 5. Build the tree.
        return self._build_tree(
            chunks=chunks,
            cluster_result=cluster_result,
            labels_by_cluster=labels_by_cluster,
            communities=communities,
            use_seed_roots=use_seed_roots,
        )

    # ------------------------------------------------------------------
    # Tree assembly
    # ------------------------------------------------------------------

    def _build_tree(
        self,
        *,
        chunks: Sequence[ChunkRecord],
        cluster_result: ClusterResult,
        labels_by_cluster: dict[int, ProposedLabel],
        communities: CommunityDetectionResult,
        use_seed_roots: bool,
    ) -> OntologyTree:
        nodes: dict[str, OntologyNode] = {}

        # Pre-compute centroid per cluster from ClusterResult (already
        # normalised to EMBEDDING_DIM by the clusterer).
        centroids: list[list[float]] = [
            list(v) for v in cluster_result.cluster_centroids
        ]

        # Pre-compute community centroids as the mean of member cluster centroids.
        community_centroids: dict[int, list[float]] = {}
        for comm in communities.communities:
            community_centroids[comm.community_id] = _mean_vec(
                [centroids[ci] for ci in comm.cluster_ids]
            )

        # 5a. Roots.
        seed_root_ids: list[str] = []
        if use_seed_roots and self.seed_taxonomy is not None:
            for t in self.seed_taxonomy.list_types():
                nid = _seed_node_id(t.name)
                node = OntologyNode(
                    id=nid,
                    parent_id=None,
                    label=t.display_name or t.name,
                    kind="seed",
                    chunk_ids=[],
                    centroid_embedding=[],
                    confidence=1.0,
                )
                nodes[nid] = node
                seed_root_ids.append(nid)
        else:
            # LLM-proposed roots: one synthetic root per community when the
            # community has any members. Communities map 1:1 to top-level
            # induced categories in this non-AEC path.
            for comm in communities.communities:
                if not comm.cluster_ids:
                    continue
                # Compose a root label from its largest cluster's proposal.
                primary_cluster = comm.cluster_ids[0]
                root_label = labels_by_cluster[primary_cluster].label
                nid = _induced_node_id("root", root_label, comm.community_id)
                centroid = community_centroids.get(comm.community_id, [])
                # If the centroid happens to not match EMBEDDING_DIM (e.g.
                # all-zero placeholder from an empty community), drop it.
                if centroid and len(centroid) != EMBEDDING_DIM:
                    centroid = []
                node = OntologyNode(
                    id=nid,
                    parent_id=None,
                    label=root_label,
                    kind="induced",
                    chunk_ids=[],
                    centroid_embedding=centroid,
                    confidence=labels_by_cluster[primary_cluster].confidence,
                )
                nodes[nid] = node

        # 5b. Community-level nodes (depth-2 in the seed-bootstrap path).
        # We only emit a community node when seeds are in play; in the
        # non-AEC path the community IS the root, so no second tier.
        community_node_ids: dict[int, str] = {}
        if use_seed_roots:
            for comm in communities.communities:
                if not comm.cluster_ids:
                    continue
                # Pick the seed root whose label best matches the
                # community's primary cluster label.
                community_label = labels_by_cluster[comm.cluster_ids[0]].label
                parent_id = self._best_seed_parent(
                    community_label, seed_root_ids, nodes
                )
                nid = _induced_node_id(
                    "category", community_label, comm.community_id
                )
                centroid = community_centroids.get(comm.community_id, [])
                if centroid and len(centroid) != EMBEDDING_DIM:
                    centroid = []
                node = OntologyNode(
                    id=nid,
                    parent_id=parent_id,
                    label=community_label,
                    kind="induced",
                    chunk_ids=[],
                    centroid_embedding=centroid,
                    confidence=labels_by_cluster[comm.cluster_ids[0]].confidence,
                )
                nodes[nid] = node
                community_node_ids[comm.community_id] = nid

        # 5c. Cluster-level leaf nodes.
        chunks_by_cluster: dict[int, list[str]] = {}
        for assn in cluster_result.assignments:
            chunks_by_cluster.setdefault(assn.cluster_id, []).append(
                assn.chunk_content_hash
            )

        for ci in range(cluster_result.num_clusters):
            label = labels_by_cluster[ci].label
            chunk_ids = chunks_by_cluster.get(ci, [])
            if not chunk_ids:
                # Skip empty clusters — k-means with degenerate seeds can
                # leave one empty; we don't materialise empty leaves.
                continue
            # Figure out parent: community node (seed path) or community-root
            # node (non-AEC path).
            comm_id = communities.community_for_cluster(ci)
            if use_seed_roots:
                if comm_id is None or comm_id not in community_node_ids:
                    # Cluster didn't end up in any community (e.g. singleton
                    # below the similarity threshold). Attach directly to the
                    # best-match seed root.
                    parent_id = self._best_seed_parent(
                        label, seed_root_ids, nodes
                    )
                else:
                    parent_id = community_node_ids[comm_id]
            else:
                if comm_id is None:
                    # Make a synthetic singleton root for this cluster.
                    syn_root_id = _induced_node_id("root", label, ci + 1000)
                    if syn_root_id not in nodes:
                        nodes[syn_root_id] = OntologyNode(
                            id=syn_root_id,
                            parent_id=None,
                            label=label,
                            kind="induced",
                            chunk_ids=[],
                            centroid_embedding=centroids[ci],
                            confidence=labels_by_cluster[ci].confidence,
                        )
                    parent_id = syn_root_id
                else:
                    parent_id = _induced_node_id(
                        "root",
                        labels_by_cluster[
                            communities.communities[comm_id].cluster_ids[0]
                        ].label,
                        comm_id,
                    )

            nid = _induced_node_id("topic", label, ci)
            node = OntologyNode(
                id=nid,
                parent_id=parent_id,
                label=label,
                kind="induced",
                chunk_ids=list(chunk_ids),
                centroid_embedding=centroids[ci],
                confidence=labels_by_cluster[ci].confidence,
            )
            nodes[nid] = node

        # In the seed-bootstrap path, prune seed roots that ended up with
        # no descendants to keep the tree compact. The non-AEC path never
        # creates an orphan root.
        if use_seed_roots:
            referenced_parents = {
                n.parent_id for n in nodes.values() if n.parent_id is not None
            }
            for rid in list(seed_root_ids):
                if rid not in referenced_parents:
                    nodes.pop(rid, None)

        return OntologyTree(nodes=nodes)

    # ------------------------------------------------------------------
    # Seed-root matching
    # ------------------------------------------------------------------

    def _best_seed_parent(
        self,
        community_label: str,
        seed_root_ids: list[str],
        nodes: dict[str, OntologyNode],
    ) -> str:
        """Pick the seed root whose name shares the most tokens with the label.

        Falls back to a stable default: the first seed root in insertion
        order (which is whatever the YAML lists first — typically
        ``contract``).
        """
        if not seed_root_ids:
            # Should not happen given callers, but defensive: return any.
            raise ValueError("no seed roots available for attachment")

        tokens = set(_WORD_RE.findall(community_label.lower()))
        best_id = seed_root_ids[0]
        best_overlap = -1
        for rid in seed_root_ids:
            node = nodes[rid]
            seed_tokens = set(_WORD_RE.findall(node.label.lower())) | set(
                _WORD_RE.findall(rid.lower())
            )
            overlap = len(tokens & seed_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = rid
        return best_id


# ----------------------------------------------------------------------
# ID helpers — stable hashes keep ids reproducible across runs.
# ----------------------------------------------------------------------


def _seed_node_id(seed_name: str) -> str:
    return f"seed:{seed_name}"


def _induced_node_id(kind: str, label: str, disambiguator: int) -> str:
    """Deterministic id from (kind, label, disambiguator).

    The disambiguator is whatever integer (cluster id, community id) ensures
    uniqueness across siblings in the tree. The hash makes ids look opaque
    so callers don't accidentally rely on their internal shape.
    """
    h = hashlib.sha1(
        f"{kind}|{label}|{disambiguator}".encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:12]
    return f"ind:{kind}:{h}"


def _mean_vec(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of a list of equal-length float lists."""
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            out[i] += v[i]
    n = float(len(vectors))
    return [x / n for x in out]


__all__ = [
    "OntologyInducer",
    "_corpus_looks_aec_shaped",  # exported for tests
    "_induced_node_id",
    "_seed_node_id",
]


# Silence the linter about the imported `_cosine` — we don't use it here, but
# keep the import so the module's public-name surface stays consistent.
_ = _cosine

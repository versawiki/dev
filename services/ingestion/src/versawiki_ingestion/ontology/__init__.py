"""Ontology induction — discover a tenant-private taxonomy from embedded chunks.

The locked pipeline (per `DECISIONS.md` 2026-05-22 and `docs/research/ontology.md`):

  1. **Cluster** chunk embeddings via BERTopic (UMAP -> HDBSCAN -> c-TF-IDF).
     In sandboxes where BERTopic isn't installable we use a numpy-only
     `SimpleEmbeddingClusterer` fallback that exposes the same Protocol.
  2. **Propose taxonomy labels** for each cluster via an LLM. Three providers
     ship: `AnthropicTaxonomyProposer`, `OpenAITaxonomyProposer`, and the
     deterministic, network-free `StubTaxonomyProposer` used in tests.
  3. **Detect communities** on a chunk-similarity graph (cosine of centroid
     embeddings) via Leiden. Same Protocol-with-fallback story as clustering;
     the fallback is `SimpleConnectedComponentsDetector`.
  4. **Assemble** an `OntologyTree` rooted in seed AEC taxonomy nodes when the
     corpus looks AEC-shaped, else rooted in LLM-proposed roots.

The resulting tree is tenant-private. The meta-MCP receives only the
*shape* of the tree (see `compute_ontology_shape` in
`services/meta-mcp`) — never labels or chunk text.
"""

from .clusterer import (
    ChunkClusterAssignment,
    ClusterResult,
    OntologyClusterer,
    SimpleEmbeddingClusterer,
)
from .community import (
    Community,
    CommunityDetectionResult,
    LeidenCommunityDetector,
    OntologyCommunityDetector,
    SimpleConnectedComponentsDetector,
)
from .inducer import OntologyInducer
from .merge import merge_with_existing
from .models import OntologyNode, OntologyTree
from .taxonomy_proposer import (
    AnthropicTaxonomyProposer,
    LLMTaxonomyProposer,
    OpenAITaxonomyProposer,
    ProposedLabel,
    StubTaxonomyProposer,
)

__all__ = [
    "AnthropicTaxonomyProposer",
    "ChunkClusterAssignment",
    "ClusterResult",
    "Community",
    "CommunityDetectionResult",
    "LLMTaxonomyProposer",
    "LeidenCommunityDetector",
    "OntologyClusterer",
    "OntologyCommunityDetector",
    "OntologyInducer",
    "OntologyNode",
    "OntologyTree",
    "OpenAITaxonomyProposer",
    "ProposedLabel",
    "SimpleConnectedComponentsDetector",
    "SimpleEmbeddingClusterer",
    "StubTaxonomyProposer",
    "merge_with_existing",
]

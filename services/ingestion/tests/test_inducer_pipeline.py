"""End-to-end test for the ontology induction pipeline.

Feeds ~50 synthetic ChunkRecords through SimpleEmbeddingClusterer + the
stub proposer + SimpleConnectedComponentsDetector + the tree builder, and
asserts the resulting `OntologyTree` has the expected shape.
"""

from __future__ import annotations

import pytest

from versawiki_ingestion.embedding.stub_provider import StubEmbeddingProvider
from versawiki_ingestion.ontology import (
    OntologyInducer,
    OntologyTree,
    SimpleEmbeddingClusterer,
)
from versawiki_ingestion.ontology.community import SimpleConnectedComponentsDetector
from versawiki_ingestion.ontology.taxonomy_proposer import StubTaxonomyProposer
from versawiki_ingestion.pipeline.models import ChunkRecord


def _make_chunk(text: str, position: int) -> ChunkRecord:
    vec = StubEmbeddingProvider._one(text)
    chunk_hash = (f"{position:064x}")[-64:]
    rec = ChunkRecord(
        tenant_id="t",
        source_id="s",
        source_uri=f"file://{position}.txt",
        document_content_hash="d" * 64,
        position=position,
        text=text,
        start_char=0,
        end_char=len(text),
        chunk_content_hash=chunk_hash,
    )
    return rec.with_embedding(vec, "stub")


@pytest.fixture
def fifty_chunk_non_aec_corpus() -> list[ChunkRecord]:
    """Synthetic corpus that does NOT trigger the AEC seed bootstrap.

    Five thematic groups, ten chunks each, no AEC signal words.
    """
    themes = [
        "telescope orbit satellite mission payload",
        "cooking recipe baking flavour pastry",
        "guitar chord progression melody scale",
        "philosophy ethics metaphysics logic argument",
        "marathon training endurance pacing hydration",
    ]
    chunks: list[ChunkRecord] = []
    pos = 0
    for theme in themes:
        for i in range(10):
            text = f"{theme} variant {i}"
            chunks.append(_make_chunk(text, pos))
            pos += 1
    return chunks


@pytest.mark.asyncio
async def test_full_pipeline_returns_ontology_tree(fifty_chunk_non_aec_corpus):
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=5, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(
            similarity_threshold=0.85
        ),
        seed_taxonomy=None,
    )
    tree = await inducer.induce(fifty_chunk_non_aec_corpus)
    assert isinstance(tree, OntologyTree)
    assert len(tree) > 0


@pytest.mark.asyncio
async def test_full_pipeline_has_root_and_depth_at_least_two(fifty_chunk_non_aec_corpus):
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=5, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(
            similarity_threshold=0.85
        ),
        seed_taxonomy=None,
    )
    tree = await inducer.induce(fifty_chunk_non_aec_corpus)
    assert len(tree.roots()) >= 1
    # Each cluster becomes a leaf under a root, so depth is at least 2.
    assert tree.depth() >= 2


@pytest.mark.asyncio
async def test_full_pipeline_no_empty_leaves(fifty_chunk_non_aec_corpus):
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=5, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(
            similarity_threshold=0.85
        ),
        seed_taxonomy=None,
    )
    tree = await inducer.induce(fifty_chunk_non_aec_corpus)
    leaves = tree.leaves()
    # Every leaf in the induced tree must carry at least one chunk.
    assert leaves, "tree has no leaves"
    for leaf in leaves:
        assert leaf.chunk_ids, f"leaf {leaf.id} has no chunk_ids"


@pytest.mark.asyncio
async def test_full_pipeline_distributes_chunks_across_nodes(
    fifty_chunk_non_aec_corpus,
):
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=5, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(
            similarity_threshold=0.85
        ),
        seed_taxonomy=None,
    )
    tree = await inducer.induce(fifty_chunk_non_aec_corpus)
    all_chunks = tree.all_chunk_ids()
    # Every chunk in the input should appear somewhere in the tree.
    expected_hashes = {c.chunk_content_hash for c in fifty_chunk_non_aec_corpus}
    assert set(all_chunks) == expected_hashes
    # Chunks should be distributed across multiple leaves, not all in one.
    leaves_with_chunks = [n for n in tree.leaves() if n.chunk_ids]
    assert len(leaves_with_chunks) >= 2


@pytest.mark.asyncio
async def test_full_pipeline_empty_corpus_returns_empty_tree():
    inducer = OntologyInducer()
    tree = await inducer.induce([])
    assert isinstance(tree, OntologyTree)
    assert len(tree) == 0
    assert tree.roots() == []


@pytest.mark.asyncio
async def test_full_pipeline_default_construction_works():
    """The dataclass defaults give a fully functional inducer."""
    inducer = OntologyInducer()
    chunks = [
        _make_chunk("telescope orbit satellite payload mission", i)
        for i in range(6)
    ]
    tree = await inducer.induce(chunks)
    assert isinstance(tree, OntologyTree)
    assert len(tree) > 0

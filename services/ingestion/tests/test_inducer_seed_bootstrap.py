"""Seed-bootstrap tests for `OntologyInducer`.

When the corpus contains enough AEC signal words, the tree's roots are
seeded from the bundled AEC starter taxonomy. Otherwise it's LLM-proposed
roots only.
"""

from __future__ import annotations

import pytest

from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.embedding.stub_provider import StubEmbeddingProvider
from versawiki_ingestion.ontology import OntologyInducer, SimpleEmbeddingClusterer
from versawiki_ingestion.ontology.community import SimpleConnectedComponentsDetector
from versawiki_ingestion.ontology.inducer import _corpus_looks_aec_shaped
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
def aec_shaped_corpus() -> list[ChunkRecord]:
    """A corpus with strong AEC signals — should trigger seed bootstrapping."""
    texts = [
        "RFI submitted regarding civil discipline response",
        "Contract amendment value subcontract amendment",
        "Drawing sheet revision discipline structural",
        "Submittal product data shop drawing electrical",
        "Specification mechanical discipline standard requirements",
    ]
    return [_make_chunk(t, i) for i, t in enumerate(texts * 4)]


@pytest.fixture
def non_aec_corpus() -> list[ChunkRecord]:
    """A corpus with no AEC signals — falls through to LLM-proposed roots."""
    texts = [
        "telescope orbit satellite mission payload",
        "cooking recipe baking flavour pastry",
        "guitar chord progression melody scale",
    ]
    return [_make_chunk(t, i) for i, t in enumerate(texts * 4)]


def test_corpus_shape_detector_recognises_aec(aec_shaped_corpus):
    assert _corpus_looks_aec_shaped(aec_shaped_corpus) is True


def test_corpus_shape_detector_rejects_non_aec(non_aec_corpus):
    assert _corpus_looks_aec_shaped(non_aec_corpus) is False


@pytest.mark.asyncio
async def test_seed_bootstrap_uses_aec_roots(aec_shaped_corpus):
    """When the corpus is AEC-shaped and a seed taxonomy is provided, root
    ids start with ``seed:``."""
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=3, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(),
        seed_taxonomy=Taxonomy.starter(),
    )
    tree = await inducer.induce(aec_shaped_corpus)
    roots = tree.roots()
    assert roots, "expected at least one root from the seed taxonomy"
    # At least one root must be seeded from the AEC taxonomy.
    seed_roots = [r for r in roots if r.kind == "seed"]
    assert seed_roots, f"no seed-kind roots found, got {[r.id for r in roots]}"
    for sr in seed_roots:
        assert sr.id.startswith("seed:")
        assert sr.confidence == 1.0


@pytest.mark.asyncio
async def test_non_aec_corpus_skips_seed_roots(non_aec_corpus):
    """If the corpus doesn't look AEC, roots are LLM-proposed (kind='induced')."""
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=3, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(),
        seed_taxonomy=Taxonomy.starter(),
    )
    tree = await inducer.induce(non_aec_corpus)
    roots = tree.roots()
    assert roots, "tree has no roots"
    for r in roots:
        assert r.kind == "induced"
        assert not r.id.startswith("seed:")


@pytest.mark.asyncio
async def test_seed_bootstrap_without_taxonomy_skips_seeds(aec_shaped_corpus):
    """No seed taxonomy provided -> never seed-bootstrap, even on AEC corpus."""
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=3, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(),
        seed_taxonomy=None,
    )
    tree = await inducer.induce(aec_shaped_corpus)
    for r in tree.roots():
        assert r.kind == "induced"


@pytest.mark.asyncio
async def test_seed_bootstrap_only_keeps_used_roots(aec_shaped_corpus):
    """Unused seed roots are pruned so the tree stays compact."""
    inducer = OntologyInducer(
        clusterer=SimpleEmbeddingClusterer(target_clusters=2, seed=0),
        proposer=StubTaxonomyProposer(),
        community_detector=SimpleConnectedComponentsDetector(),
        seed_taxonomy=Taxonomy.starter(),
    )
    tree = await inducer.induce(aec_shaped_corpus)
    seed_taxonomy = Taxonomy.starter()
    # We should not see all 11 seed types as roots — only the ones that
    # received children.
    seed_root_ids = {r.id for r in tree.roots() if r.kind == "seed"}
    assert len(seed_root_ids) < len(seed_taxonomy.list_types())
    # Every kept seed root has at least one descendant.
    for sid in seed_root_ids:
        kids = tree.children_of(sid)
        assert kids, f"seed root {sid} kept despite having no children"

"""Tests for `SimpleEmbeddingClusterer` — the numpy-only fallback clusterer."""

from __future__ import annotations

import math

import pytest

from versawiki_ingestion.embedding.base import EMBEDDING_DIM
from versawiki_ingestion.embedding.stub_provider import StubEmbeddingProvider
from versawiki_ingestion.ontology.clusterer import (
    OntologyClusterer,
    SimpleEmbeddingClusterer,
)
from versawiki_ingestion.pipeline.models import ChunkRecord


def _make_chunk(text: str, position: int, vec: list[float] | None = None) -> ChunkRecord:
    chunk_hash = (f"{position:064x}")[-64:]
    doc_hash = "d" * 64
    rec = ChunkRecord(
        tenant_id="t1",
        source_id="s1",
        source_uri=f"file://{position}.txt",
        document_content_hash=doc_hash,
        position=position,
        text=text,
        start_char=0,
        end_char=len(text),
        chunk_content_hash=chunk_hash,
    )
    if vec is None:
        return rec
    return rec.with_embedding(vec, "stub")


@pytest.fixture
def synthetic_clusters() -> list[ChunkRecord]:
    """Build a corpus with three obvious clusters using the StubEmbeddingProvider.

    Same text -> same embedding -> same cluster, deterministically.
    """
    chunks: list[ChunkRecord] = []
    base_texts = [
        "Contract value parties amendment subcontract",
        "RFI question discipline civil response submitted",
        "Drawing sheet number revision discipline issued",
    ]
    pos = 0
    for base in base_texts:
        for variant_i in range(6):
            text = f"{base} variant_{variant_i}"
            vec = StubEmbeddingProvider._one(text)
            chunks.append(_make_chunk(text, pos, vec))
            pos += 1
    return chunks


def test_clusterer_returns_clusters_for_each_assignment(synthetic_clusters):
    clusterer = SimpleEmbeddingClusterer(target_clusters=3, seed=0)
    result = clusterer.cluster(synthetic_clusters)
    assert len(result.assignments) == 18
    assert result.num_clusters == 3
    for centroid in result.cluster_centroids:
        assert len(centroid) == EMBEDDING_DIM


def test_clusterer_empty_corpus_returns_empty_result():
    clusterer = SimpleEmbeddingClusterer()
    result = clusterer.cluster([])
    assert result.assignments == []
    assert result.cluster_centroids == []
    assert result.noise_chunks == []
    assert result.num_clusters == 0


def test_clusterer_drops_chunks_without_embeddings(synthetic_clusters):
    unembedded = _make_chunk("no embedding here", 999)
    clusterer = SimpleEmbeddingClusterer(target_clusters=2, seed=0)
    result = clusterer.cluster(list(synthetic_clusters) + [unembedded])
    hashes = {a.chunk_content_hash for a in result.assignments}
    assert unembedded.chunk_content_hash not in hashes


def test_clusterer_deterministic_with_same_seed(synthetic_clusters):
    r1 = SimpleEmbeddingClusterer(target_clusters=3, seed=42).cluster(synthetic_clusters)
    r2 = SimpleEmbeddingClusterer(target_clusters=3, seed=42).cluster(synthetic_clusters)
    assert [(a.chunk_content_hash, a.cluster_id) for a in r1.assignments] == [
        (a.chunk_content_hash, a.cluster_id) for a in r2.assignments
    ]


def test_clusterer_protocol_compliance():
    clusterer = SimpleEmbeddingClusterer()
    assert isinstance(clusterer, OntologyClusterer)
    assert clusterer.name == "simple-kmeans"


def test_clusterer_target_clusters_validated():
    with pytest.raises(ValueError):
        SimpleEmbeddingClusterer(target_clusters=0)
    with pytest.raises(ValueError):
        SimpleEmbeddingClusterer(max_iter=0)


def test_clusterer_assigns_similar_embeddings_to_same_cluster():
    """Hand-built vectors near three orthogonal centroids should partition
    cleanly. (We don't use `StubEmbeddingProvider` here because its
    sha256-derived vectors have no semantic-similarity structure.)"""
    import random

    rng = random.Random(0)
    chunks: list[ChunkRecord] = []
    centers = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    pos = 0
    expected_groups: list[set[str]] = [set(), set(), set()]
    for gi, center in enumerate(centers):
        for _ in range(6):
            vec = [0.0] * EMBEDDING_DIM
            for i, v in enumerate(center):
                vec[i] = v
            for i in range(EMBEDDING_DIM):
                vec[i] += rng.uniform(-0.05, 0.05)
            chunk = _make_chunk(f"text {pos}", pos, vec)
            chunks.append(chunk)
            expected_groups[gi].add(chunk.chunk_content_hash)
            pos += 1
    clusterer = SimpleEmbeddingClusterer(target_clusters=3, seed=0)
    result = clusterer.cluster(chunks)
    by_cluster: dict[int, set[str]] = {}
    for assn in result.assignments:
        by_cluster.setdefault(assn.cluster_id, set()).add(assn.chunk_content_hash)
    for group in expected_groups:
        clusters_hit = {ci for ci, hs in by_cluster.items() if hs & group}
        assert len(clusters_hit) == 1


def test_clusterer_validates_embedding_dimension():
    bad_vec = [0.1] * 32
    chunk = ChunkRecord(
        tenant_id="t",
        source_id="s",
        source_uri="file://x",
        document_content_hash="d" * 64,
        position=0,
        text="hi",
        start_char=0,
        end_char=2,
        chunk_content_hash="c" * 64,
        embedding=bad_vec,
        embedding_provider="bogus",
    )
    with pytest.raises(ValueError):
        SimpleEmbeddingClusterer().cluster([chunk])


def test_clusterer_centroids_match_member_means(synthetic_clusters):
    """The centroid of a cluster should be the mean of its members."""
    clusterer = SimpleEmbeddingClusterer(target_clusters=3, seed=0)
    result = clusterer.cluster(synthetic_clusters)
    by_hash = {c.chunk_content_hash: c for c in synthetic_clusters}
    for ci in range(result.num_clusters):
        members = [
            by_hash[a.chunk_content_hash].embedding
            for a in result.assignments
            if a.cluster_id == ci
        ]
        if not members:
            continue
        expected = [sum(v[i] for v in members) / len(members) for i in range(EMBEDDING_DIM)]
        centroid = result.cluster_centroids[ci]
        for a, b in zip(expected, centroid):
            assert math.isclose(a, b, abs_tol=1e-9)

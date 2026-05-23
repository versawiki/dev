"""Tests for `StubTaxonomyProposer` — the deterministic, no-network proposer."""

from __future__ import annotations

import pytest

from versawiki_ingestion.embedding.base import EMBEDDING_DIM
from versawiki_ingestion.embedding.stub_provider import StubEmbeddingProvider
from versawiki_ingestion.ontology.clusterer import (
    ChunkClusterAssignment,
    ClusterResult,
    SimpleEmbeddingClusterer,
)
from versawiki_ingestion.ontology.taxonomy_proposer import (
    LLMTaxonomyProposer,
    ProposedLabel,
    StubTaxonomyProposer,
)
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


@pytest.mark.asyncio
async def test_stub_proposer_returns_label_per_cluster():
    chunks = [
        _make_chunk("contract value parties subcontract", 0),
        _make_chunk("contract amendment task order", 1),
        _make_chunk("RFI question discipline civil response", 2),
        _make_chunk("RFI submitted response discipline mechanical", 3),
    ]
    cluster_result = SimpleEmbeddingClusterer(target_clusters=2, seed=0).cluster(chunks)
    proposer = StubTaxonomyProposer()
    labels = await proposer.propose(cluster_result, chunks)
    assert len(labels) == cluster_result.num_clusters
    for label in labels:
        assert isinstance(label, ProposedLabel)
        assert label.label.startswith("cluster_") or label.label == "cluster_"
        assert 0.0 <= label.confidence <= 1.0


@pytest.mark.asyncio
async def test_stub_proposer_deterministic():
    chunks = [
        _make_chunk("contract value parties subcontract", 0),
        _make_chunk("RFI question discipline civil", 1),
    ]
    cluster_result = ClusterResult(
        assignments=[
            ChunkClusterAssignment(chunks[0].chunk_content_hash, 0),
            ChunkClusterAssignment(chunks[1].chunk_content_hash, 1),
        ],
        cluster_centroids=[[0.0] * EMBEDDING_DIM, [0.0] * EMBEDDING_DIM],
        noise_chunks=[],
    )
    a = await StubTaxonomyProposer().propose(cluster_result, chunks)
    b = await StubTaxonomyProposer().propose(cluster_result, chunks)
    assert [l.label for l in a] == [l.label for l in b]


@pytest.mark.asyncio
async def test_stub_proposer_picks_top_tokens():
    chunks = [
        _make_chunk("contract contract contract value", 0),
        _make_chunk("contract amendment value contract", 1),
    ]
    cluster_result = ClusterResult(
        assignments=[
            ChunkClusterAssignment(chunks[0].chunk_content_hash, 0),
            ChunkClusterAssignment(chunks[1].chunk_content_hash, 0),
        ],
        cluster_centroids=[[0.0] * EMBEDDING_DIM],
        noise_chunks=[],
    )
    labels = await StubTaxonomyProposer().propose(cluster_result, chunks)
    assert "contract" in labels[0].label


@pytest.mark.asyncio
async def test_stub_proposer_empty_cluster_gets_placeholder():
    cluster_result = ClusterResult(
        assignments=[],
        cluster_centroids=[[0.0] * EMBEDDING_DIM, [0.0] * EMBEDDING_DIM],
        noise_chunks=[],
    )
    labels = await StubTaxonomyProposer().propose(cluster_result, [])
    # One label per cluster even with no member chunks.
    assert len(labels) == 2
    assert labels[0].label == "cluster_0"
    assert labels[1].label == "cluster_1"


@pytest.mark.asyncio
async def test_stub_proposer_skips_stopwords_and_short_tokens():
    # The text is mostly stopwords; only `versawiki` should make it through.
    chunks = [_make_chunk("the and for with versawiki versawiki versawiki", 0)]
    cluster_result = ClusterResult(
        assignments=[ChunkClusterAssignment(chunks[0].chunk_content_hash, 0)],
        cluster_centroids=[[0.0] * EMBEDDING_DIM],
        noise_chunks=[],
    )
    labels = await StubTaxonomyProposer().propose(cluster_result, chunks)
    assert "versawiki" in labels[0].label


def test_stub_proposer_protocol_compliance():
    proposer = StubTaxonomyProposer()
    assert isinstance(proposer, LLMTaxonomyProposer)
    assert proposer.name == "stub"

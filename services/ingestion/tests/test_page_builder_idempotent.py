"""Determinism test: same inputs -> same outputs.

We're using ``StubPageWriter`` which is fully deterministic, so the
markdown body should hash to the same value across runs given the
same inputs. This guard catches accidental introduction of timestamps
or random ids into the rendered body.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from versawiki_ingestion.embedding.stub_provider import StubEmbeddingProvider
from versawiki_ingestion.ontology.models import OntologyNode
from versawiki_ingestion.pages import PageBuilder, StubPageWriter
from versawiki_ingestion.pipeline.models import ChunkRecord


def _make_chunk(text: str, position: int) -> ChunkRecord:
    chunk_hash = (f"{position:064x}")[-64:]
    rec = ChunkRecord(
        tenant_id="t1",
        source_id="s1",
        source_uri=f"file://chunk_{position}.txt",
        document_content_hash=("d" * 64),
        position=position,
        text=text,
        start_char=0,
        end_char=len(text),
        chunk_content_hash=chunk_hash,
    )
    return rec.with_embedding(StubEmbeddingProvider._one(text), "stub")


@pytest.fixture
def node_and_chunks():
    chunks = [_make_chunk(f"rfi item {i}", i) for i in range(4)]
    vecs = [c.embedding for c in chunks]
    dim = len(vecs[0])
    centroid = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
    node = OntologyNode(
        id="ind:topic:deadbeefdead",
        parent_id=None,
        label="rfi_topic",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in chunks],
        centroid_embedding=centroid,
        confidence=0.9,
    )
    return node, chunks


@pytest.mark.asyncio
async def test_same_inputs_same_body_hash(node_and_chunks):
    node, chunks = node_and_chunks
    # Pin `now` so the Metadata section's timestamp doesn't drift.
    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    builder_a = PageBuilder(llm_writer=StubPageWriter())
    builder_b = PageBuilder(llm_writer=StubPageWriter())
    page_a = await builder_a.build_for_node(
        node, chunks, {}, tenant_id="t1", now=now
    )
    page_b = await builder_b.build_for_node(
        node, chunks, {}, tenant_id="t1", now=now
    )
    h_a = hashlib.sha256(page_a.body_markdown.encode("utf-8")).hexdigest()
    h_b = hashlib.sha256(page_b.body_markdown.encode("utf-8")).hexdigest()
    assert h_a == h_b


@pytest.mark.asyncio
async def test_same_inputs_same_title_and_slug(node_and_chunks):
    node, chunks = node_and_chunks
    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    builder = PageBuilder(llm_writer=StubPageWriter())
    page_a = await builder.build_for_node(
        node, chunks, {}, tenant_id="t1", now=now
    )
    page_b = await builder.build_for_node(
        node, chunks, {}, tenant_id="t1", now=now
    )
    assert page_a.title == page_b.title
    assert page_a.slug == page_b.slug
    assert page_a.id == page_b.id


@pytest.mark.asyncio
async def test_chunk_order_canonicalised(node_and_chunks):
    """Shuffled input chunks produce the same final order (ranker is stable)."""
    node, chunks = node_and_chunks
    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)
    builder = PageBuilder(llm_writer=StubPageWriter())
    page_a = await builder.build_for_node(
        node, chunks, {}, tenant_id="t1", now=now
    )
    page_b = await builder.build_for_node(
        node, list(reversed(chunks)), {}, tenant_id="t1", now=now
    )
    assert page_a.chunk_ids == page_b.chunk_ids
    assert page_a.body_markdown == page_b.body_markdown

"""Threshold tests: small nodes are rolled up; big nodes get pages.

The pipeline-level decision lives in `PageBuildPipeline`. We test it
here against a tiny synthetic tree so the rollup behaviour is pinned.
"""

from __future__ import annotations

import pytest

from versawiki_ingestion.embedding.stub_provider import StubEmbeddingProvider
from versawiki_ingestion.ontology.models import OntologyNode, OntologyTree
from versawiki_ingestion.pages import (
    InMemoryPageStore,
    PageBuildPipeline,
    PageBuilder,
    StubPageWriter,
)
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


@pytest.mark.asyncio
async def test_node_with_one_chunk_no_page_produced():
    # Two nodes: a parent with no chunks, a child with exactly one
    # chunk. The child should be rolled up; the parent then has one
    # chunk total, which is still below threshold, so still no page.
    parent = OntologyNode(
        id="parent",
        parent_id=None,
        label="parent_topic",
        kind="induced",
        chunk_ids=[],
        centroid_embedding=[],
        confidence=0.8,
    )
    child_chunk = _make_chunk("loner chunk", 0)
    child = OntologyNode(
        id="child",
        parent_id="parent",
        label="child_topic",
        kind="induced",
        chunk_ids=[child_chunk.chunk_content_hash],
        centroid_embedding=[],
        confidence=0.7,
    )
    tree = OntologyTree(nodes={"parent": parent, "child": child})
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=InMemoryPageStore(),
    )
    pages = await pipeline.build_for_tree(
        tree, [child_chunk], {}, tenant_id="t1"
    )
    assert pages == []


@pytest.mark.asyncio
async def test_node_with_two_chunks_gets_page():
    chunks = [_make_chunk("topic alpha", i) for i in range(2)]
    node = OntologyNode(
        id="topic_node",
        parent_id=None,
        label="alpha_topic",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in chunks],
        centroid_embedding=[],
        confidence=0.85,
    )
    tree = OntologyTree(nodes={node.id: node})
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=InMemoryPageStore(),
    )
    pages = await pipeline.build_for_tree(
        tree, chunks, {}, tenant_id="t1"
    )
    assert len(pages) == 1
    assert pages[0].ontology_node_id == node.id


@pytest.mark.asyncio
async def test_small_leaf_rolled_into_parent():
    # Parent with 1 chunk, child with 1 chunk. After rollup the
    # parent has 2 chunks and qualifies for a page; the child stays
    # leaf-only.
    parent_chunk = _make_chunk("parent direct chunk", 0)
    child_chunk = _make_chunk("child direct chunk", 1)
    parent = OntologyNode(
        id="parent",
        parent_id=None,
        label="parent_topic",
        kind="induced",
        chunk_ids=[parent_chunk.chunk_content_hash],
        centroid_embedding=[],
        confidence=0.9,
    )
    child = OntologyNode(
        id="child",
        parent_id="parent",
        label="child_topic",
        kind="induced",
        chunk_ids=[child_chunk.chunk_content_hash],
        centroid_embedding=[],
        confidence=0.8,
    )
    tree = OntologyTree(nodes={"parent": parent, "child": child})
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=InMemoryPageStore(),
    )
    pages = await pipeline.build_for_tree(
        tree, [parent_chunk, child_chunk], {}, tenant_id="t1"
    )
    assert len(pages) == 1
    assert pages[0].ontology_node_id == "parent"
    # Both chunks are reachable via the parent page.
    assert parent_chunk.chunk_content_hash in pages[0].chunk_ids
    assert child_chunk.chunk_content_hash in pages[0].chunk_ids


@pytest.mark.asyncio
async def test_custom_threshold_is_respected():
    # With threshold=3, a node with 2 chunks should NOT get a page.
    chunks = [_make_chunk(f"chunk {i}", i) for i in range(2)]
    node = OntologyNode(
        id="topic_node",
        parent_id=None,
        label="alpha_topic",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in chunks],
        centroid_embedding=[],
        confidence=0.85,
    )
    tree = OntologyTree(nodes={node.id: node})
    pipeline = PageBuildPipeline(
        builder=PageBuilder(
            llm_writer=StubPageWriter(),
            min_chunks_for_page=3,
        ),
        store=InMemoryPageStore(),
        min_chunks_for_page=3,
    )
    pages = await pipeline.build_for_tree(
        tree, chunks, {}, tenant_id="t1"
    )
    assert pages == []

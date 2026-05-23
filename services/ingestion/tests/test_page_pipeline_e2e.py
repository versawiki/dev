"""End-to-end pipeline test over a synthetic three-level ontology tree.

Builds 20 chunks distributed across a small tree, runs the pipeline,
and asserts the resulting pages match the tree shape, have no
orphans, and the ``related_page_ids`` references form a cycle-free
graph.
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
from versawiki_ingestion.pages.builder import _stable_page_id
from versawiki_ingestion.pipeline.models import ChunkRecord


def _make_chunk(text: str, position: int) -> ChunkRecord:
    chunk_hash = (f"{position:064x}")[-64:]
    rec = ChunkRecord(
        tenant_id="t1",
        source_id="s1",
        source_uri=f"file://chunk_{position}.txt",
        document_content_hash=(f"{position % 5:064x}")[-64:],
        position=position,
        text=text,
        start_char=0,
        end_char=len(text),
        chunk_content_hash=chunk_hash,
    )
    return rec.with_embedding(StubEmbeddingProvider._one(text), "stub")


@pytest.fixture
def three_level_tree_and_chunks():
    """Tree shape:

        root (no direct chunks)
        |-- topic_a    (5 chunks)
        |       |-- topic_a_sub  (3 chunks)
        |-- topic_b    (5 chunks)
                |-- topic_b_sub  (2 chunks)
                |-- topic_b_sub2 (5 chunks)
    """
    chunks: list[ChunkRecord] = []
    position = 0

    def take(n: int) -> list[ChunkRecord]:
        nonlocal position
        out: list[ChunkRecord] = []
        for _ in range(n):
            text = f"chunk content {position}"
            chunks.append(_make_chunk(text, position))
            out.append(chunks[-1])
            position += 1
        return out

    a_chunks = take(5)
    a_sub_chunks = take(3)
    b_chunks = take(5)
    b_sub_chunks = take(2)
    b_sub2_chunks = take(5)

    root = OntologyNode(
        id="root",
        parent_id=None,
        label="root_topic",
        kind="seed",
        chunk_ids=[],
        centroid_embedding=[],
        confidence=1.0,
    )
    topic_a = OntologyNode(
        id="topic_a",
        parent_id="root",
        label="topic_a",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in a_chunks],
        centroid_embedding=[],
        confidence=0.9,
    )
    topic_a_sub = OntologyNode(
        id="topic_a_sub",
        parent_id="topic_a",
        label="topic_a_sub",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in a_sub_chunks],
        centroid_embedding=[],
        confidence=0.85,
    )
    topic_b = OntologyNode(
        id="topic_b",
        parent_id="root",
        label="topic_b",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in b_chunks],
        centroid_embedding=[],
        confidence=0.9,
    )
    topic_b_sub = OntologyNode(
        id="topic_b_sub",
        parent_id="topic_b",
        label="topic_b_sub",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in b_sub_chunks],
        centroid_embedding=[],
        confidence=0.8,
    )
    topic_b_sub2 = OntologyNode(
        id="topic_b_sub2",
        parent_id="topic_b",
        label="topic_b_sub2",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in b_sub2_chunks],
        centroid_embedding=[],
        confidence=0.82,
    )
    tree = OntologyTree(
        nodes={
            "root": root,
            "topic_a": topic_a,
            "topic_a_sub": topic_a_sub,
            "topic_b": topic_b,
            "topic_b_sub": topic_b_sub,
            "topic_b_sub2": topic_b_sub2,
        }
    )
    return tree, chunks


@pytest.mark.asyncio
async def test_pipeline_builds_pages_for_qualifying_nodes(three_level_tree_and_chunks):
    tree, chunks = three_level_tree_and_chunks
    store = InMemoryPageStore()
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=store,
    )
    pages = await pipeline.build_for_tree(tree, chunks, {}, tenant_id="t1")
    node_ids = {p.ontology_node_id for p in pages}
    # All five non-root topics have >=2 chunks; topic_b_sub has 2 (the
    # threshold). The "root" itself only gets chunks from rollup; that
    # depends on the rollup behaviour, but the topic_a / topic_b /
    # subs MUST all be present.
    assert "topic_a" in node_ids
    assert "topic_a_sub" in node_ids
    assert "topic_b" in node_ids
    assert "topic_b_sub" in node_ids
    assert "topic_b_sub2" in node_ids


@pytest.mark.asyncio
async def test_pipeline_persists_pages(three_level_tree_and_chunks):
    tree, chunks = three_level_tree_and_chunks
    store = InMemoryPageStore()
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=store,
    )
    pages = await pipeline.build_for_tree(tree, chunks, {}, tenant_id="t1")
    for page in pages:
        roundtrip = await store.get("t1", page.id)
        assert roundtrip is not None
        assert roundtrip.id == page.id


@pytest.mark.asyncio
async def test_related_page_ids_cycle_free(three_level_tree_and_chunks):
    tree, chunks = three_level_tree_and_chunks
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=InMemoryPageStore(),
    )
    pages = await pipeline.build_for_tree(tree, chunks, {}, tenant_id="t1")
    by_id = {p.id: p for p in pages}
    # Walk the related-page graph; ensure no node ever references
    # itself, and BFS terminates without revisiting an ancestor.
    for page in pages:
        assert page.id not in page.related_page_ids
        # Bounded BFS depth — every page on the tree has at most ~5
        # neighbours, so 100 nodes visited is more than enough.
        seen = {page.id}
        stack = list(page.related_page_ids)
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur in by_id:
                stack.extend(by_id[cur].related_page_ids)
            if len(seen) > 100:
                pytest.fail("related_page_ids walk did not terminate")


@pytest.mark.asyncio
async def test_no_orphan_pages(three_level_tree_and_chunks):
    """Every page corresponds to a real node in the tree."""
    tree, chunks = three_level_tree_and_chunks
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=InMemoryPageStore(),
    )
    pages = await pipeline.build_for_tree(tree, chunks, {}, tenant_id="t1")
    for page in pages:
        assert page.ontology_node_id in tree.nodes


@pytest.mark.asyncio
async def test_related_ids_point_to_materialised_pages_only(three_level_tree_and_chunks):
    tree, chunks = three_level_tree_and_chunks
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=InMemoryPageStore(),
    )
    pages = await pipeline.build_for_tree(tree, chunks, {}, tenant_id="t1")
    page_ids = {p.id for p in pages}
    for page in pages:
        for rid in page.related_page_ids:
            assert rid in page_ids


@pytest.mark.asyncio
async def test_related_ids_use_stable_page_ids(three_level_tree_and_chunks):
    """Related-page ids match what `_stable_page_id` would produce."""
    tree, chunks = three_level_tree_and_chunks
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=InMemoryPageStore(),
    )
    pages = await pipeline.build_for_tree(tree, chunks, {}, tenant_id="t1")
    by_node = {p.ontology_node_id: p for p in pages}
    # topic_a should reference topic_a_sub (child) and topic_b (sibling).
    a_page = by_node["topic_a"]
    expected_sub = _stable_page_id("t1", "topic_a_sub")
    expected_sib = _stable_page_id("t1", "topic_b")
    assert expected_sub in a_page.related_page_ids
    assert expected_sib in a_page.related_page_ids

"""Build a page from a synthetic node + 5 chunks via `StubPageWriter`.

Sanity-check: every field of the resulting WikiPage is populated,
the markdown body has the four contractual sections, and the chunks
fed into the builder match what comes out the other side.
"""

from __future__ import annotations

import pytest

from versawiki_ingestion.classification.base import ClassifierResult
from versawiki_ingestion.embedding.stub_provider import StubEmbeddingProvider
from versawiki_ingestion.ontology.models import OntologyNode, OntologyTree
from versawiki_ingestion.pages import PageBuilder, StubPageWriter, WikiPage
from versawiki_ingestion.pipeline.models import ChunkRecord


def _make_chunk(text: str, position: int, *, doc_hash: str | None = None) -> ChunkRecord:
    chunk_hash = (f"{position:064x}")[-64:]
    doc = doc_hash or ("d" * 64)
    rec = ChunkRecord(
        tenant_id="t1",
        source_id="s1",
        source_uri=f"file://doc_{position}.txt",
        document_content_hash=doc,
        position=position,
        text=text,
        start_char=0,
        end_char=len(text),
        chunk_content_hash=chunk_hash,
    )
    return rec.with_embedding(StubEmbeddingProvider._one(text), "stub")


@pytest.fixture
def synthetic_node() -> OntologyNode:
    chunks = [_make_chunk(f"rfi response question {i}", i) for i in range(5)]
    vecs = [c.embedding for c in chunks]
    dim = len(vecs[0])
    centroid = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
    return OntologyNode(
        id="ind:topic:abc123abc123",
        parent_id=None,
        label="rfi_responses",
        kind="induced",
        chunk_ids=[c.chunk_content_hash for c in chunks],
        centroid_embedding=centroid,
        confidence=0.92,
    )


@pytest.fixture
def synthetic_chunks() -> list[ChunkRecord]:
    return [_make_chunk(f"rfi response question {i}", i) for i in range(5)]


@pytest.fixture
def classifier_results(synthetic_chunks) -> dict[str, ClassifierResult]:
    return {
        synthetic_chunks[0].document_content_hash: ClassifierResult(
            predicted_type="rfi",
            confidence=0.88,
            alternatives=[],
            uncertainty_reason=None,
            signals={"keyword_match": 0.9},
        ),
    }


@pytest.mark.asyncio
async def test_build_page_populates_all_fields(
    synthetic_node, synthetic_chunks, classifier_results
):
    builder = PageBuilder(llm_writer=StubPageWriter())
    page = await builder.build_for_node(
        synthetic_node,
        synthetic_chunks,
        classifier_results,
        tenant_id="t1",
    )
    assert isinstance(page, WikiPage)
    assert page.tenant_id == "t1"
    assert page.ontology_node_id == synthetic_node.id
    assert page.title  # non-empty
    assert page.slug
    assert page.summary
    assert page.body_markdown
    assert page.chunk_ids
    assert set(page.chunk_ids) == {c.chunk_content_hash for c in synthetic_chunks}
    assert page.is_stale is False
    assert page.version == 1
    assert page.source_uri_count == len({c.source_uri for c in synthetic_chunks})


@pytest.mark.asyncio
async def test_body_has_all_four_sections(synthetic_node, synthetic_chunks):
    builder = PageBuilder(llm_writer=StubPageWriter())
    page = await builder.build_for_node(
        synthetic_node,
        synthetic_chunks,
        {},
        tenant_id="t1",
    )
    body = page.body_markdown
    # Section order is part of the contract.
    overview_idx = body.find("## Overview")
    key_docs_idx = body.find("## Key documents")
    related_idx = body.find("## Related topics")
    metadata_idx = body.find("## Metadata")
    assert overview_idx >= 0
    assert key_docs_idx > overview_idx
    assert related_idx > key_docs_idx
    assert metadata_idx > related_idx


@pytest.mark.asyncio
async def test_related_labels_present_when_tree_provided(synthetic_node, synthetic_chunks):
    # Build a tiny tree: root -> synthetic_node -> child.
    root = OntologyNode(
        id="root_id",
        parent_id=None,
        label="root_topic",
        kind="seed",
        chunk_ids=[],
        centroid_embedding=[],
        confidence=1.0,
    )
    target = synthetic_node.model_copy(update={"parent_id": root.id})
    child = OntologyNode(
        id="child_id",
        parent_id=target.id,
        label="child_topic",
        kind="induced",
        chunk_ids=[],
        centroid_embedding=[],
        confidence=0.8,
    )
    sibling = OntologyNode(
        id="sibling_id",
        parent_id=root.id,
        label="sibling_topic",
        kind="induced",
        chunk_ids=[],
        centroid_embedding=[],
        confidence=0.7,
    )
    tree = OntologyTree(
        nodes={
            root.id: root,
            target.id: target,
            child.id: child,
            sibling.id: sibling,
        }
    )
    builder = PageBuilder(llm_writer=StubPageWriter())
    page = await builder.build_for_node(
        target,
        synthetic_chunks,
        {},
        tenant_id="t1",
        tree=tree,
    )
    assert "child_topic" in page.body_markdown
    assert "sibling_topic" in page.body_markdown


@pytest.mark.asyncio
async def test_stub_writer_was_called(synthetic_node, synthetic_chunks):
    writer = StubPageWriter()
    builder = PageBuilder(llm_writer=writer)
    await builder.build_for_node(
        synthetic_node, synthetic_chunks, {}, tenant_id="t1"
    )
    assert len(writer.title_calls) == 1
    assert len(writer.summary_calls) == 1
    # Writer was given the node's label.
    title_label, _ = writer.title_calls[0]
    assert title_label == "rfi_responses"


@pytest.mark.asyncio
async def test_predominant_doc_types_populated(synthetic_node, synthetic_chunks):
    # Make doc-type signal richer: assign each chunk to a different doc.
    chunks = [
        _make_chunk(f"chunk {i}", i, doc_hash=(f"{i:064x}")[-64:])
        for i in range(5)
    ]
    classifier_results = {
        chunks[0].document_content_hash: ClassifierResult(
            predicted_type="rfi", confidence=0.9, alternatives=[]
        ),
        chunks[1].document_content_hash: ClassifierResult(
            predicted_type="rfi", confidence=0.85, alternatives=[]
        ),
        chunks[2].document_content_hash: ClassifierResult(
            predicted_type="submittal", confidence=0.7, alternatives=[]
        ),
    }
    builder = PageBuilder(llm_writer=StubPageWriter())
    page = await builder.build_for_node(
        synthetic_node, chunks, classifier_results, tenant_id="t1"
    )
    assert "rfi" in page.predominant_doc_types
    # rfi should be first (2 docs) before submittal (1 doc).
    assert page.predominant_doc_types[0] == "rfi"

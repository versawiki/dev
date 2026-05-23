"""Pipeline integration: process_document emits chunks + ClassifierResult."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from versawiki_ingestion.chunking import Chunker, RecursiveCharacterSplitter
from versawiki_ingestion.classification import (
    ClassifierResult,
    DocumentClassifier,
    StubLLMClassifier,
)
from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
from versawiki_ingestion.embedding import StubEmbeddingProvider
from versawiki_ingestion.parsers.registry import ParserRegistry
from versawiki_ingestion.pipeline import ProcessedDocument, process_document


@pytest.mark.asyncio
async def test_pipeline_emits_chunks_and_classification(make_corpus: Callable[..., Path]) -> None:
    text = (
        "RFI 042 — concrete mix design.\n\n"
        + ("submitted_by Jane Doe; assigned_to structural team; response pending. " * 80)
    )
    root = make_corpus({"rfi_042.txt": text})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    classifier = DocumentClassifier(
        StubLLMClassifier(), taxonomy=Taxonomy.starter()
    )

    out = await process_document(
        ref,
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(text_splitter=RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=40)),
        embedding_provider=StubEmbeddingProvider(),
        classifier=classifier,
    )

    assert isinstance(out, ProcessedDocument)
    assert len(out.chunks) >= 2
    assert isinstance(out.classification, ClassifierResult)
    # Heuristic stub should pick rfi for an rfi-shaped file.
    assert out.classification.predicted_type == "rfi"
    # Signals are present (orchestrator populates the bounded vocabulary).
    for key in (
        "header_match_score",
        "keyword_density",
        "structural_complexity",
        "llm_confidence",
        "heuristic_agreement",
        "alt_count",
    ):
        assert key in out.classification.signals
        assert 0.0 <= out.classification.signals[key] <= 1.0


@pytest.mark.asyncio
async def test_pipeline_classification_is_deterministic_given_stub(
    make_corpus: Callable[..., Path],
) -> None:
    """Same fixture, same stub LLM, same orchestrator -> identical classification."""
    text = (
        "RFI submitted_by Jane; assigned_to structural team; question about concrete. " * 50
    )
    root = make_corpus({"rfi_042.txt": text})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    classifier_a = DocumentClassifier(StubLLMClassifier())
    classifier_b = DocumentClassifier(StubLLMClassifier())

    args = dict(
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(text_splitter=RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=40)),
        embedding_provider=StubEmbeddingProvider(),
    )

    a = await process_document(ref, **args, classifier=classifier_a)
    b = await process_document(ref, **args, classifier=classifier_b)

    assert a.classification == b.classification
    assert [r.chunk_content_hash for r in a.chunks] == [r.chunk_content_hash for r in b.chunks]


@pytest.mark.asyncio
async def test_pipeline_classification_passes_document_type_to_chunker_metadata(
    make_corpus: Callable[..., Path],
) -> None:
    """The chunker receives the classifier's predicted_type, not the parser's
    fallback document_type. Verified via chunk metadata."""
    text = "RFI 042 about concrete mix design. " * 100
    root = make_corpus({"rfi_042.txt": text})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    out = await process_document(
        ref,
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(),
        embedding_provider=StubEmbeddingProvider(),
    )

    assert out.classification is not None
    # Every chunk's metadata carries the predicted document_type.
    for rec in out.chunks:
        assert rec.metadata.get("document_type") == out.classification.predicted_type


@pytest.mark.asyncio
async def test_pipeline_empty_doc_yields_empty_processed_document(
    make_corpus: Callable[..., Path],
) -> None:
    root = make_corpus({"empty.txt": ""})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    out = await process_document(
        ref,
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(),
        embedding_provider=StubEmbeddingProvider(),
    )
    assert out.chunks == []
    assert out.classification is None
    # Back-compat: bool(empty) is False.
    assert not out


@pytest.mark.asyncio
async def test_pipeline_short_circuit_when_known_hash(
    make_corpus: Callable[..., Path],
) -> None:
    root = make_corpus({"doc.txt": "Some payload."})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    first = await process_document(
        ref,
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(),
        embedding_provider=StubEmbeddingProvider(),
    )
    known_hash = first.chunks[0].document_content_hash

    second = await process_document(
        ref,
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(),
        embedding_provider=StubEmbeddingProvider(),
        known_hashes={known_hash},
    )
    assert second.chunks == []
    assert second.classification is None
    # Back-compat: empty ProcessedDocument == [].
    assert second == []

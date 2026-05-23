"""End-to-end pipeline test: connector + parser + chunker + stub embedder.

This is the integration test that proves the whole `process_document` flow
hangs together: bytes in (from the LocalFolderConnector), `ChunkRecord`s out,
each with a 1024-dim embedding attached. Also covers the idempotency
short-circuit on `known_hashes`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

import pytest

from versawiki_ingestion.chunking import Chunker, RecursiveCharacterSplitter
from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
from versawiki_ingestion.embedding import EMBEDDING_DIM, StubEmbeddingProvider
from versawiki_ingestion.parsers.registry import ParserRegistry
from versawiki_ingestion.pipeline import process_document


@pytest.mark.asyncio
async def test_process_document_emits_chunks_with_embeddings(
    make_corpus: Callable[..., Path],
) -> None:
    # Big enough text that the splitter produces multiple chunks.
    big_text = (
        "Project kickoff meeting notes.\n\n"
        + ("Discussion of structural drawings and submittal logs. " * 80)
        + "\n\n"
        + ("Action items: file RFI 042, review concrete mix design. " * 80)
    )
    root = make_corpus({"notes.txt": big_text})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    chunker = Chunker(text_splitter=RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=50))
    provider = StubEmbeddingProvider()

    records = await process_document(
        ref,
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=chunker,
        embedding_provider=provider,
    )

    assert len(records) >= 2  # multiple chunks
    # Each chunk has a 1024-dim embedding and the right provider tag.
    for rec in records:
        assert rec.embedding is not None
        assert len(rec.embedding) == EMBEDDING_DIM
        assert rec.embedding_provider == "stub"
        assert rec.tenant_id == "t1"
        assert rec.source_id == "s1"
        assert rec.source_uri == "notes.txt"
        # document_content_hash is the same on every chunk of one document.
        assert rec.document_content_hash == records[0].document_content_hash
    # Positions are monotonic 0..N-1.
    assert [r.position for r in records] == list(range(len(records)))


@pytest.mark.asyncio
async def test_process_document_short_circuits_on_known_hash(
    make_corpus: Callable[..., Path],
) -> None:
    payload = "Some content that gets ingested twice."
    root = make_corpus({"a.txt": payload})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    chunker = Chunker()
    provider = StubEmbeddingProvider()
    registry = ParserRegistry.default()

    first = await process_document(
        ref,
        connector=conn,
        parser_registry=registry,
        chunker=chunker,
        embedding_provider=provider,
    )
    assert first  # non-empty
    known_hash = first[0].document_content_hash
    # Computed independently from the raw bytes.
    assert known_hash == hashlib.sha256(payload.encode("utf-8")).hexdigest()

    second = await process_document(
        ref,
        connector=conn,
        parser_registry=registry,
        chunker=chunker,
        embedding_provider=provider,
        known_hashes={known_hash},
    )
    assert second == []


@pytest.mark.asyncio
async def test_process_document_handles_empty_text(
    make_corpus: Callable[..., Path],
) -> None:
    root = make_corpus({"empty.txt": ""})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())
    records = await process_document(
        ref,
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(),
        embedding_provider=StubEmbeddingProvider(),
    )
    assert records == []


@pytest.mark.asyncio
async def test_process_document_is_idempotent_on_chunk_hashes(
    make_corpus: Callable[..., Path],
) -> None:
    """Two runs against the same file produce identical chunk_content_hashes."""
    text = ("Some longer content to force multiple chunks. " * 60) + "\n\n" + (
        "Second paragraph with more material. " * 60
    )
    root = make_corpus({"doc.txt": text})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    args = dict(
        connector=conn,
        parser_registry=ParserRegistry.default(),
        chunker=Chunker(text_splitter=RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=40)),
        embedding_provider=StubEmbeddingProvider(),
    )

    a = await process_document(ref, **args)
    b = await process_document(ref, **args)
    assert [r.chunk_content_hash for r in a] == [r.chunk_content_hash for r in b]
    assert [r.embedding for r in a] == [r.embedding for r in b]

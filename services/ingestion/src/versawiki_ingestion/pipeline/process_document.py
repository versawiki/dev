"""End-to-end document processing: connector -> parser -> classifier -> chunker -> embedder.

Idempotency contract:

- Computes the document's `content_hash` from the connector's bytes (sha256).
- If `known_hashes` is provided and the hash is in it, returns an empty
  `ProcessedDocument` — the caller short-circuits a re-ingest. This is how
  BE-03's persistence layer will prevent re-embedding documents that haven't
  changed.

Classifier slot (M1-ING-03):
- After parsing succeeds, `DocumentClassifier.classify(parsed_doc)` is called
  and the result is attached to the `ProcessedDocument`. The classifier is
  optional — if none is supplied the function falls back to a default
  `DocumentClassifier(StubLLMClassifier())` so the upstream chunker still gets
  a populated `document_type` while keeping the pipeline deterministic.

The function deliberately accepts dependencies as parameters rather than
constructing them itself, so a worker can wire in alternative implementations
(e.g. a custom Chunker per tenant once domain-specific chunking lands).
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..chunking import Chunker
from ..classification import ClassifierResult, DocumentClassifier
from ..connectors._models import ResourceRef
from ..embedding.base import EmbeddingProvider
from ..parsers.base import ParseResult
from ..parsers.registry import ParserRegistry
from .models import ChunkRecord


class _ConnectorLike(Protocol):
    """The bits of `Connector` we actually need here (just `fetch`)."""

    def fetch(self, ref: ResourceRef) -> bytes: ...


class ProcessedDocument(BaseModel):
    """Result of running one resource through the pipeline.

    Iteration / len / indexing on a `ProcessedDocument` proxy to `chunks` so
    callers that previously treated `process_document`'s return as a list of
    `ChunkRecord` continue to work. New callers should read `.chunks` and
    `.classification` explicitly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    chunks: list[ChunkRecord] = Field(default_factory=list)
    classification: Optional[ClassifierResult] = None

    # ---- list-like proxy ------------------------------------------------

    def __iter__(self) -> Iterator[ChunkRecord]:  # type: ignore[override]
        return iter(self.chunks)

    def __len__(self) -> int:
        return len(self.chunks)

    def __bool__(self) -> bool:
        return bool(self.chunks)

    def __getitem__(self, idx: int) -> ChunkRecord:
        return self.chunks[idx]

    def __eq__(self, other: object) -> bool:
        # Allow `assert second == []` (back-compat) while still supporting
        # ProcessedDocument-to-ProcessedDocument equality.
        if isinstance(other, ProcessedDocument):
            return (
                self.chunks == other.chunks
                and self.classification == other.classification
            )
        if isinstance(other, list):
            return self.chunks == other
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return NotImplemented  # type: ignore[return-value]
        return not result

    __hash__ = None  # type: ignore[assignment]


async def process_document(
    ref: ResourceRef,
    *,
    connector: _ConnectorLike,
    parser_registry: ParserRegistry,
    chunker: Chunker,
    embedding_provider: EmbeddingProvider,
    classifier: Optional[DocumentClassifier] = None,
    known_hashes: Optional[set[str]] = None,
    extra_metadata: Optional[dict[str, Any]] = None,
) -> ProcessedDocument:
    """Process one resource end-to-end.

    Returns an empty `ProcessedDocument` (falsy, `len()==0`) if the doc is
    already known or yields no usable text.
    """
    raw = connector.fetch(ref)
    document_content_hash = hashlib.sha256(raw).hexdigest()
    if known_hashes is not None and document_content_hash in known_hashes:
        return ProcessedDocument()

    parser = parser_registry.for_ref(ref)
    if parser is None:
        # No parser -> treat as plain text via the GeneralTextParser fallback.
        # Resolve by extension last-resort; falls through to None if even that
        # has no match (e.g. binary blob with no registered handler).
        parser = parser_registry.for_extension(ref.extension)
    if parser is None:
        return ProcessedDocument()

    parse_result = _parse_bytes_via_tempfile(parser, ref, raw)
    text = parse_result.full_text
    if not text.strip():
        return ProcessedDocument()

    # Classifier slot — between parse and chunk. Default keeps deterministic
    # behaviour for upstream tests (chunker idempotency depends on this).
    active_classifier = classifier or DocumentClassifier()
    classification = await active_classifier.classify(parse_result, source_uri=ref.uri)

    chunk_specs = chunker.chunk(
        text,
        mime_type=ref.mime_type,
        extension=ref.extension,
        document_type=classification.predicted_type,
        extra_metadata=extra_metadata,
    )
    if not chunk_specs:
        return ProcessedDocument(classification=classification)

    vectors = await embedding_provider.embed([c.text for c in chunk_specs])
    if len(vectors) != len(chunk_specs):
        raise RuntimeError(
            f"Embedding provider returned {len(vectors)} vectors for "
            f"{len(chunk_specs)} chunks (provider={embedding_provider.provider_name})"
        )

    records: list[ChunkRecord] = []
    for spec, vec in zip(chunk_specs, vectors, strict=True):
        record = ChunkRecord(
            tenant_id=ref.tenant_id,
            source_id=ref.source_id,
            source_uri=ref.uri,
            document_content_hash=document_content_hash,
            position=spec.position,
            text=spec.text,
            start_char=spec.start_char,
            end_char=spec.end_char,
            chunk_content_hash=spec.content_hash,
            metadata=dict(spec.metadata),
        ).with_embedding(vec, embedding_provider.provider_name)
        records.append(record)
    return ProcessedDocument(chunks=records, classification=classification)


def _parse_bytes_via_tempfile(parser, ref: ResourceRef, raw: bytes) -> ParseResult:
    """Most parsers want a Path; write `raw` to a tempfile and parse from there.

    A future refactor can teach parsers to accept bytes directly; for M1 we
    reuse the existing parser surface as-is.
    """
    suffix = ref.extension or ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        return parser.parse(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

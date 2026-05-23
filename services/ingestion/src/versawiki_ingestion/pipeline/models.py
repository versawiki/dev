"""Records the pipeline emits, ready for the BE-03 SQLAlchemy mappers to insert.

These models intentionally mirror the column shape sketched in
`docs/architecture/v1.md` §2 (chunks, document, embedding):

- `chunks(id, document_id, ordinal, text, token_count, embedding vector(1024), metadata)`
- (chunks.embedding is the embedding vector; in this codebase we keep it on a
  separate `ChunkRecord` -> `EmbeddingRecord` pair so the pipeline can ship the
  chunk first and the embedding second if a provider call fails halfway.)

`ChunkRecord` is the cross-package contract. The Backend ticket BE-03 will
adapt these into SQLAlchemy rows; the meta-MCP ticket consumes them via the
ingestion-event bus. Keep the shape stable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..embedding.base import EMBEDDING_DIM


class IngestionJob(BaseModel):
    """A queue-shaped job ID + the resource it should ingest.

    The actual queue (RQ in production, `InProcessQueue` in tests) stores
    these as serialised JSON and rehydrates on the worker side.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    tenant_id: str
    source_id: str
    resource_uri: str
    enqueued_at: datetime


class ChunkRecord(BaseModel):
    """One chunk in flight through the pipeline, optionally with an embedding attached.

    Keyed identity is `(tenant_id, source_id, document_content_hash, position)`.
    `chunk_content_hash` is the per-chunk dedup key (a chunk that re-appears
    verbatim across documents will produce the same hash).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    source_id: str
    source_uri: str
    document_content_hash: str = Field(..., min_length=64, max_length=64)
    position: int = Field(..., ge=0)
    text: str
    start_char: int = Field(..., ge=0)
    end_char: int = Field(..., ge=0)
    chunk_content_hash: str = Field(..., min_length=64, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Optional because the pipeline may emit chunks before embeddings (resume
    # safety) and tests can assert chunk shape independently of embeddings.
    embedding: Optional[list[float]] = Field(default=None)
    embedding_provider: Optional[str] = Field(default=None)

    def with_embedding(self, vector: list[float], provider_name: str) -> "ChunkRecord":
        """Return a copy with the embedding attached. Validates dimension."""
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(
                f"ChunkRecord embedding has dim={len(vector)}; expected {EMBEDDING_DIM}"
            )
        return self.model_copy(
            update={
                "embedding": list(vector),
                "embedding_provider": provider_name,
            }
        )


class EmbeddingRecord(BaseModel):
    """Standalone embedding row — when chunk + embedding are persisted separately."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    chunk_content_hash: str = Field(..., min_length=64, max_length=64)
    embedding: list[float]
    provider_name: str

    def model_post_init(self, _ctx: Any) -> None:
        if len(self.embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"EmbeddingRecord has dim={len(self.embedding)}; expected {EMBEDDING_DIM}"
            )

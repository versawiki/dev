"""`EmbeddingProvider` Protocol and the single source-of-truth `EMBEDDING_DIM`.

Versawiki commits to a 1024-dim embedding space across the entire stack:
`chunks.embedding vector(1024)`, `ontology_nodes.embedding vector(1024)`,
`query_log.query_embedding vector(1024)`. The provider can change (OpenAI
`text-embedding-3-large` truncated via Matryoshka in M1; bge-m3 or
nomic-embed-text-v2 self-hosted before M3) but the dimension must not — a
dimension change is a schema migration plus a full corpus re-embed.

To make that contract impossible to violate by accident, every provider must
expose a `dimension` attribute equal to this module-level constant. The
`assert_dimension()` helper enforces it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# THE locked dimension. Do not introduce a second 1024 literal anywhere in the
# embedding stack — reference this constant. See DECISIONS.md 2026-05-22.
EMBEDDING_DIM: int = 1024


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Async interface every embedding provider implements.

    Implementations are responsible for:
    - Batching (most APIs charge per call; we batch up to a provider-specific
      max, e.g. 100 for OpenAI).
    - Retries on transient failures (429, 5xx).
    - Failing fast on configuration errors (missing API key) at first call,
      not at import time — so a process that never embeds doesn't need the key.

    Implementations are NOT responsible for chunking (that's `chunking/`) or
    persistence (that's the pipeline's job).
    """

    dimension: int  # MUST equal EMBEDDING_DIM at construction time.
    provider_name: str  # e.g. "openai", "stub", "bge-m3", "nomic".

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, in order.

        Each returned vector has length `self.dimension` (== EMBEDDING_DIM).
        Implementations MAY internally split `texts` into provider-specific
        batches; the caller sees one logical list-in, list-out.

        Determinism: providers that hit an external model are subject to that
        model's stability guarantees. `StubEmbeddingProvider` is fully
        deterministic and used in tests where exact-equality matters.
        """
        ...


def assert_dimension(vector: list[float], *, where: str = "embedding") -> None:
    """Defensive guard the persistence layer uses before INSERT.

    Cheap to call; catches a misconfigured provider before it pollutes pgvector.
    """
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(
            f"{where} has dim={len(vector)}; expected EMBEDDING_DIM={EMBEDDING_DIM}"
        )

"""StubEmbeddingProvider — deterministic, network-free, for tests.

The pipeline's tests must be fast and offline. This stub gives the same vector
for the same text every time, lets tests pin exact behaviour without mocking
HTTP, and lives in the production package (not under `tests/`) so other
services (api, meta-mcp) can reuse it in their own tests.
"""

from __future__ import annotations

import hashlib
import struct

from .base import EMBEDDING_DIM, EmbeddingProvider


class StubEmbeddingProvider(EmbeddingProvider):
    """Deterministic pseudo-embedding provider.

    Strategy: hash the input text with sha256, then expand the digest into a
    fixed-length float vector by treating successive 4-byte chunks as unsigned
    integers and normalising to [-1, 1]. Repeated until we have `EMBEDDING_DIM`
    floats. Same text -> identical vector across processes and platforms.

    NOT cryptographically meaningful. NOT a real semantic embedding. Use only
    in tests.
    """

    provider_name = "stub"

    def __init__(self) -> None:
        self.dimension = EMBEDDING_DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    # ------------------------------------------------------------------

    @staticmethod
    def _one(text: str) -> list[float]:
        # We need EMBEDDING_DIM floats; each sha256 yields 32 bytes -> 8 floats.
        floats_per_digest = 8
        rounds = (EMBEDDING_DIM + floats_per_digest - 1) // floats_per_digest
        out: list[float] = []
        seed = text.encode("utf-8")
        for i in range(rounds):
            digest = hashlib.sha256(seed + i.to_bytes(2, "big")).digest()
            # 8 unsigned ints, big-endian, each 4 bytes.
            for u in struct.unpack(">8I", digest):
                # Map to [-1.0, 1.0] deterministically.
                out.append(((u / 0xFFFFFFFF) * 2.0) - 1.0)
        return out[:EMBEDDING_DIM]

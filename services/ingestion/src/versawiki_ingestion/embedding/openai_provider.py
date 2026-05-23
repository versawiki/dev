"""OpenAIEmbeddingProvider — calls `text-embedding-3-large` truncated to 1024 dims.

Why truncate (Matryoshka):
    `text-embedding-3-large` is natively 3072. OpenAI's API accepts a
    `dimensions` parameter that returns Matryoshka-truncated vectors (the
    leading N dimensions remain semantically meaningful). Locking dim=1024
    keeps us swap-compatible with `bge-m3` and `nomic-embed-text-v2` later
    (DECISIONS.md 2026-05-22).

Why call the REST API directly rather than `openai` SDK:
    1) No extra dep — `httpx` is already in the stack (DECISIONS.md FastAPI/RQ).
    2) The SDK adds retry semantics we'd have to override anyway.
    3) Reduces blast radius if OpenAI's SDK breaks API compatibility.

Retry policy:
    Exponential backoff on 429 (rate limit) and 5xx (server). Max 3 attempts
    total. Base delay 1s, doubles each attempt (1, 2, 4 sleep on the failures
    before attempts 2, 3 — no sleep after the third failure; we raise).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

from .base import EMBEDDING_DIM, EmbeddingProvider


OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_MODEL = "text-embedding-3-large"
MAX_BATCH = 100  # OpenAI hard-limits embeddings inputs to <=2048; 100 is comfortable.
MAX_ATTEMPTS = 3
BASE_BACKOFF_S = 1.0


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embeddings via the REST API, Matryoshka-truncated to 1024 dims.

    The API key is *not* read at construction time — only on the first call to
    `embed()`. This lets the rest of the system import this module (e.g. for
    `get_embedding_provider("openai", ...)`) without an env var present, and
    fail loudly only when someone actually tries to embed.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        max_batch: int = MAX_BATCH,
        max_attempts: int = MAX_ATTEMPTS,
        base_backoff_s: float = BASE_BACKOFF_S,
        # Hook for tests: swap `asyncio.sleep` for an instant no-op so retry
        # paths can be exercised without slowing the suite.
        sleep: Any = asyncio.sleep,
    ) -> None:
        self.dimension = EMBEDDING_DIM
        self.model = model
        self._api_key = api_key  # may be None; resolved lazily.
        self._client = client  # optional injected client (tests)
        self._owns_client = client is None
        self.max_batch = max_batch
        self.max_attempts = max_attempts
        self.base_backoff_s = base_backoff_s
        self._sleep = sleep

    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = self._resolve_api_key()
        client = self._client or httpx.AsyncClient(timeout=60.0)
        try:
            out: list[list[float]] = []
            for start in range(0, len(texts), self.max_batch):
                batch = texts[start : start + self.max_batch]
                vectors = await self._embed_batch(client, api_key, batch)
                out.extend(vectors)
            return out
        finally:
            if self._owns_client:
                await client.aclose()

    # ------------------------------------------------------------------

    def _resolve_api_key(self) -> str:
        key = self._api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAIEmbeddingProvider: OPENAI_API_KEY is not set. "
                "Set the env var or pass api_key=... to the provider."
            )
        return key

    async def _embed_batch(
        self, client: httpx.AsyncClient, api_key: str, batch: list[str]
    ) -> list[list[float]]:
        """One request, with retries on 429 / 5xx."""
        payload = {
            "model": self.model,
            "input": batch,
            "dimensions": EMBEDDING_DIM,  # Matryoshka truncation request.
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = await client.post(
                    OPENAI_EMBEDDINGS_URL, json=payload, headers=headers
                )
            except httpx.HTTPError as e:
                last_exc = e
                if attempt >= self.max_attempts:
                    raise
                await self._sleep(self.base_backoff_s * (2 ** (attempt - 1)))
                continue

            if resp.status_code == 200:
                return self._parse_response(resp.json(), expected=len(batch))
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_exc = _HTTPStatusError(resp.status_code, resp.text)
                if attempt >= self.max_attempts:
                    raise last_exc
                await self._sleep(self.base_backoff_s * (2 ** (attempt - 1)))
                continue
            # Non-retryable (4xx other than 429). Raise immediately.
            raise _HTTPStatusError(resp.status_code, resp.text)

        # Should be unreachable, but keep mypy happy.
        if last_exc:
            raise last_exc
        raise RuntimeError("OpenAIEmbeddingProvider: exhausted retries with no error")

    @staticmethod
    def _parse_response(body: dict[str, Any], *, expected: int) -> list[list[float]]:
        data = body.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise ValueError(
                f"OpenAI embeddings response malformed: expected {expected} entries, got "
                f"{len(data) if isinstance(data, list) else type(data).__name__}"
            )
        # `data` items have `index` and `embedding`. Sort by index defensively.
        ordered = sorted(data, key=lambda d: d.get("index", 0))
        vectors: list[list[float]] = []
        for item in ordered:
            emb = item.get("embedding")
            if not isinstance(emb, list) or len(emb) != EMBEDDING_DIM:
                raise ValueError(
                    f"OpenAI returned vector with dim={len(emb) if isinstance(emb, list) else '?'}; "
                    f"expected {EMBEDDING_DIM}"
                )
            vectors.append([float(x) for x in emb])
        return vectors


class _HTTPStatusError(RuntimeError):
    """Internal error wrapping a non-2xx HTTP status."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"OpenAI embeddings HTTP {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body

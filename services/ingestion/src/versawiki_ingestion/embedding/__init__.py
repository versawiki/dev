"""Embedding providers and registry.

The pipeline stays model-agnostic: it talks to `EmbeddingProvider`s and never
imports a concrete provider directly. See `DECISIONS.md` (2026-05-22 embedding
plumbing entry) for why dimension is locked at 1024 and model swaps are cheap.
"""

from .base import EMBEDDING_DIM, EmbeddingProvider
from .openai_provider import OpenAIEmbeddingProvider
from .registry import get_embedding_provider
from .stub_provider import StubEmbeddingProvider

__all__ = [
    "EMBEDDING_DIM",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "StubEmbeddingProvider",
    "get_embedding_provider",
]

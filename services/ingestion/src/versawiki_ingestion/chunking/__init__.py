"""Chunking strategies that split parsed document text into embeddable units.

The chunker is the single most important component for idempotency: every
downstream artifact (embeddings, ontology assignments, wiki pages) is keyed
by `(document_id, chunk.position)` or `chunk.content_hash`. Same input must
always produce the same chunks — see `tests/test_chunking.py` for the three
idempotency tests that gate this.
"""

from .base import ChunkSpec, normalize_text
from .chunker import Chunker
from .code_splitter import CodeSplitter
from .text_splitter import RecursiveCharacterSplitter

__all__ = [
    "ChunkSpec",
    "Chunker",
    "CodeSplitter",
    "RecursiveCharacterSplitter",
    "normalize_text",
]

"""CodeSplitter — placeholder until M1-ING-04 brings tree-sitter into the stack.

For now, code-flavoured documents (``.py``, ``.ts``, ``.go``, ...) fall back
to a wider-window `RecursiveCharacterSplitter(chunk_size=2000, chunk_overlap=200)`.
The wider window matters because code semantically clusters by function /
class boundaries, which are typically 1–2k characters. Once M1-ING-04 lands,
this class is the swap point — its public surface (`split(text)` returning
`list[ChunkSpec]`) is what `Chunker` calls, and the implementation switches
without touching anything upstream.
"""

from __future__ import annotations

from typing import Any

from .base import ChunkSpec
from .text_splitter import RecursiveCharacterSplitter


class CodeSplitter:
    """Code-aware splitter. Currently a wider character splitter; tree-sitter swap is M1-ING-04."""

    def __init__(
        self,
        *,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ) -> None:
        # Compose the recursive splitter to avoid divergence in chunking semantics
        # between code and text in the interim — both go through the same packer.
        self._inner = RecursiveCharacterSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(
        self, text: str, *, extra_metadata: dict[str, Any] | None = None
    ) -> list[ChunkSpec]:
        meta: dict[str, Any] = {"splitter": "code_fallback"}
        if extra_metadata:
            meta.update(extra_metadata)
        chunks = self._inner.split(text, extra_metadata=meta)
        # Overwrite splitter tag (the inner one sets it to "recursive").
        return [c.model_copy(update={"metadata": {**c.metadata, "splitter": "code_fallback"}}) for c in chunks]

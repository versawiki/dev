"""`Chunker` — chooses a splitter based on MIME / extension, returns ChunkSpecs.

Selection policy (cheap, deterministic, easy to reason about):

  1. If the MIME type starts with ``text/x-``, ``application/x-`` and contains
     a known code marker (``-python``, ``-typescript``, ``-go``, ...), OR the
     file extension is in `CODE_EXTENSIONS`, use the `CodeSplitter`.
  2. Otherwise, use the `RecursiveCharacterSplitter`.

This matches the M1 ticket's note that code is a future enhancement; the
selection logic exists today so the swap to tree-sitter is invisible to
upstream callers.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import ChunkSpec
from .code_splitter import CodeSplitter
from .text_splitter import RecursiveCharacterSplitter


# Extensions that route to the code splitter. Conservative; expand as needed.
CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".swift",
        ".php",
        ".sh",
        ".bash",
        ".zsh",
        ".sql",
    }
)


class Chunker:
    """Picks a splitter per (mime, extension) and produces `ChunkSpec`s."""

    def __init__(
        self,
        *,
        text_splitter: Optional[RecursiveCharacterSplitter] = None,
        code_splitter: Optional[CodeSplitter] = None,
    ) -> None:
        self.text_splitter = text_splitter or RecursiveCharacterSplitter()
        self.code_splitter = code_splitter or CodeSplitter()

    def chunk(
        self,
        text: str,
        *,
        mime_type: Optional[str] = None,
        extension: Optional[str] = None,
        document_type: Optional[str] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> list[ChunkSpec]:
        """Split `text` using the splitter chosen for the given hints.

        Args:
            text: The full document text to split.
            mime_type: MIME hint from the parser, e.g. ``"text/markdown"``.
            extension: File extension hint, lowercase with leading dot, e.g. ``".py"``.
            document_type: Parser's `ParseResult.document_type` (informational
                for now; reserved for parser-aware splitting later).
            extra_metadata: Extra keys merged into each `ChunkSpec.metadata`.

        Returns:
            A list of `ChunkSpec`s in document order.
        """
        if self._is_code(mime_type=mime_type, extension=extension):
            base_meta: dict[str, Any] = {}
            if document_type:
                base_meta["document_type"] = document_type
            if extra_metadata:
                base_meta.update(extra_metadata)
            return self.code_splitter.split(text, extra_metadata=base_meta or None)

        base_meta = {}
        if document_type:
            base_meta["document_type"] = document_type
        if extra_metadata:
            base_meta.update(extra_metadata)
        return self.text_splitter.split(text, extra_metadata=base_meta or None)

    # ------------------------------------------------------------------

    @staticmethod
    def _is_code(*, mime_type: Optional[str], extension: Optional[str]) -> bool:
        if extension and extension.lower() in CODE_EXTENSIONS:
            return True
        if mime_type:
            m = mime_type.lower()
            if m.startswith("text/x-") or m.startswith("application/x-"):
                # Pull off marker substring.
                if any(
                    marker in m
                    for marker in (
                        "python",
                        "typescript",
                        "javascript",
                        "go",
                        "rust",
                        "java",
                        "kotlin",
                        "ruby",
                        "c++",
                        "csharp",
                        "swift",
                        "php",
                        "shellscript",
                        "sql",
                    )
                ):
                    return True
        return False

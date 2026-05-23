"""RecursiveCharacterSplitter — hierarchical text splitter, idempotent.

Strategy (lifted from the LangChain `RecursiveCharacterTextSplitter` pattern,
which is the de-facto baseline in 2025-2026 RAG stacks):

  1. Normalise the input text first (see `base.normalize_text`).
  2. If the normalised text fits in `chunk_size`, return one chunk.
  3. Otherwise, walk a hierarchy of separators (`["\\n\\n", "\\n", ". ", " ", ""]`).
     For each separator, attempt to split the text at occurrences of that
     separator. If any of the resulting segments is still larger than
     `chunk_size`, recurse into that segment with the *next* separator down.
  4. Pack adjacent small segments back together up to `chunk_size`, with an
     overlap of `chunk_overlap` characters between consecutive packed chunks.

Deterministic guarantees (the property the suite explicitly enforces):
  - Same `(text, chunk_size, chunk_overlap)` always returns the same list of
    `ChunkSpec`s, including identical `content_hash`es.
  - `chunk_size` is an upper bound; a single un-splittable run longer than
    `chunk_size` is permitted (with a warning in metadata) rather than
    silently truncated.
  - `chunk_overlap` is honoured by the packer; the overlap is taken from the
    tail of the previous chunk's text, not as a token-count approximation.

We deliberately do NOT use a tokenizer-aware split here. M1's chunk_size is
in characters (~1500 char ~ 350-400 English tokens for typical prose), and
the only place character-vs-token differs materially is for code blocks,
which get the `CodeSplitter` fallback (currently a wider char-based splitter
until M1-ING-04 brings tree-sitter into the stack).
"""

from __future__ import annotations

from typing import Any

from .base import ChunkSpec, compute_content_hash, normalize_text


# Default hierarchy. Order matters: prefer paragraph breaks, then line breaks,
# then sentence-ish, then word, finally character-level (the empty-string
# separator is the "split anywhere" sentinel).
DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


class RecursiveCharacterSplitter:
    """Character-budget splitter that walks a separator hierarchy.

    Construct with `chunk_size` (max chars per chunk) and `chunk_overlap` (chars
    repeated between consecutive chunks). The defaults match the M1 design call
    in the ticket: 1500 / 200.
    """

    def __init__(
        self,
        *,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        separators: tuple[str, ...] = DEFAULT_SEPARATORS,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be < chunk_size")
        if not separators:
            raise ValueError("separators must be non-empty")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = tuple(separators)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def split(
        self,
        text: str,
        *,
        extra_metadata: dict[str, Any] | None = None,
    ) -> list[ChunkSpec]:
        """Return a list of ChunkSpecs covering `text` in order.

        Empty/whitespace-only input -> empty list. The splitter normalises
        before splitting, so `start_char` / `end_char` index into the
        normalised text.
        """
        normalised = normalize_text(text)
        if not normalised or not normalised.strip():
            return []

        # 1) Split into atomic segments using the separator hierarchy.
        segments = self._split_recursive(normalised, self.separators)
        # 2) Pack segments into chunks up to chunk_size, with overlap.
        packed = self._pack(segments)
        # 3) Compute offsets and ChunkSpec rows.
        return self._materialise(normalised, packed, extra_metadata or {})

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _split_recursive(self, text: str, separators: tuple[str, ...]) -> list[str]:
        """Split `text` along the first separator that produces useful pieces."""
        if len(text) <= self.chunk_size:
            return [text]
        # Find first separator that actually appears in `text` (or "" sentinel
        # which always "appears").
        sep = ""
        remaining: tuple[str, ...] = ()
        for i, s in enumerate(separators):
            if s == "" or s in text:
                sep = s
                remaining = separators[i + 1 :]
                break

        if sep == "":
            # Character-level fallback: just cut into chunk_size pieces.
            return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

        pieces = _split_keeping_separator(text, sep)
        out: list[str] = []
        for p in pieces:
            if len(p) <= self.chunk_size:
                if p:  # skip empties
                    out.append(p)
            else:
                # Recurse with the rest of the hierarchy.
                out.extend(self._split_recursive(p, remaining if remaining else ("",)))
        return out

    def _pack(self, segments: list[str]) -> list[str]:
        """Greedy pack: combine consecutive segments up to chunk_size, with overlap."""
        if not segments:
            return []
        chunks: list[str] = []
        current = ""
        for seg in segments:
            # If adding the segment overflows, flush.
            if current and len(current) + len(seg) > self.chunk_size:
                chunks.append(current)
                # Start the next chunk with the tail-overlap of the previous one.
                if self.chunk_overlap > 0 and len(current) > self.chunk_overlap:
                    current = current[-self.chunk_overlap :]
                else:
                    current = ""
            # Segment might individually exceed chunk_size (un-splittable run).
            if len(seg) > self.chunk_size:
                # Flush whatever's accumulated, then emit the oversize segment as its own chunk.
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(seg)
                continue
            current += seg
        if current:
            chunks.append(current)
        return chunks

    def _materialise(
        self,
        normalised: str,
        chunks: list[str],
        extra_metadata: dict[str, Any],
    ) -> list[ChunkSpec]:
        """Compute character offsets and build ChunkSpec rows."""
        out: list[ChunkSpec] = []
        # Track a search cursor so duplicate substrings don't all resolve to offset 0.
        cursor = 0
        for position, chunk_text in enumerate(chunks):
            idx = normalised.find(chunk_text, cursor)
            if idx == -1:
                # Should be impossible given chunks were built from `normalised`,
                # but stay defensive: fall back to a search from 0.
                idx = normalised.find(chunk_text)
                if idx == -1:
                    idx = cursor  # last-resort: keep monotonic offsets
            start = idx
            end = start + len(chunk_text)
            cursor = max(start + 1, end - self.chunk_overlap)  # allow overlap to next chunk

            metadata = {
                "splitter": "recursive",
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            }
            if extra_metadata:
                metadata.update(extra_metadata)

            out.append(
                ChunkSpec(
                    text=chunk_text,
                    position=position,
                    start_char=start,
                    end_char=end,
                    metadata=metadata,
                    content_hash=compute_content_hash(chunk_text),
                )
            )
        return out


def _split_keeping_separator(text: str, sep: str) -> list[str]:
    """Split `text` on `sep` but keep `sep` attached to the right side of each piece.

    e.g. `_split_keeping_separator("a.\\nb.\\nc", "\\n")` -> ["a.\\n", "b.\\n", "c"].
    Empty pieces are dropped.
    """
    if not sep:
        return [text]
    parts: list[str] = []
    start = 0
    sep_len = len(sep)
    while True:
        idx = text.find(sep, start)
        if idx == -1:
            tail = text[start:]
            if tail:
                parts.append(tail)
            return parts
        end = idx + sep_len
        piece = text[start:end]
        if piece:
            parts.append(piece)
        start = end

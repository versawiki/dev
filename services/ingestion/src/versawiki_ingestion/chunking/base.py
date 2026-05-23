"""`ChunkSpec` value object plus shared text-normalisation helper.

`ChunkSpec` is what splitters return and what the pipeline turns into
`ChunkRecord` rows. Frozen + extra=forbid so a typo in metadata names fails
loudly rather than silently writing junk to pgvector. `content_hash` is a
stable sha256 of the normalised text — equal hash means equal text means the
downstream pipeline can short-circuit re-embedding.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# Normalisation rules used both by splitters and by `compute_content_hash`.
# Keeping these as module-level constants so a future tweak is a one-line diff
# rather than a hunt across files.
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")
_MULTIPLE_BLANK_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Canonicalise text before hashing or splitting.

    The contract: any two strings that should be treated as "the same chunk
    content" must normalise to the same byte sequence. Used both inside the
    splitter (so chunk boundaries are stable) and by `compute_content_hash`.
    """
    # NFC unicode normalisation — handles "é" written as one code point vs.
    # "e + combining accent" without altering visible text.
    out = unicodedata.normalize("NFC", text)
    # Convert CRLF / CR to LF.
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing whitespace at end of each line.
    out = _TRAILING_WS_RE.sub("\n", out)
    # Collapse runs of 3+ blank lines down to 2 (one blank between paragraphs
    # is the canonical form).
    out = _MULTIPLE_BLANK_RE.sub("\n\n", out)
    return out


def compute_content_hash(text: str) -> str:
    """sha256(normalize_text(text)).hexdigest(). Stable across processes."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


class ChunkSpec(BaseModel):
    """One chunk of text produced by a splitter, ready for embedding.

    Boundaries (`start_char`, `end_char`) are character offsets into the
    splitter's *input* string (post-normalisation when the splitter normalises
    before slicing — `RecursiveCharacterSplitter` does). `position` is the
    ordinal of this chunk within the document, starting at 0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(..., description="The chunk's content, post-normalisation.")
    position: int = Field(..., ge=0, description="0-based ordinal within the document.")
    start_char: int = Field(..., ge=0)
    end_char: int = Field(..., ge=0)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Splitter-set hints, e.g. {'splitter': 'recursive', 'separator': '\\n\\n'}. "
            "Forwarded into chunk.metadata at persistence time."
        ),
    )
    content_hash: str = Field(
        ...,
        description="sha256 of normalize_text(self.text). Deterministic dedup key.",
        min_length=64,
        max_length=64,
    )

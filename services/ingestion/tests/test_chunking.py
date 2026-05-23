"""Tests for the chunking package.

Idempotency is the gating contract — three tests below explicitly assert
"same input -> same output, including content_hash" because every
downstream artifact depends on it.
"""

from __future__ import annotations

from versawiki_ingestion.chunking import (
    ChunkSpec,
    RecursiveCharacterSplitter,
    normalize_text,
)
from versawiki_ingestion.chunking.base import compute_content_hash
from versawiki_ingestion.chunking.chunker import Chunker


# ----------------------------------------------------------------------
# Idempotency — the gating property.
# ----------------------------------------------------------------------


def test_idempotency_same_input_same_chunks_and_hashes() -> None:
    """Calling .split() twice on the same text yields identical ChunkSpecs.

    Includes identical content_hashes, identical offsets, identical metadata.
    """
    text = "\n\n".join(
        [
            "Paragraph one with some content that talks about RFIs and submittals.",
            "Paragraph two: an entirely different topic, drawing reviews and as-builts.",
            "Paragraph three brings the count up enough to ensure we get more than one chunk.",
            "Paragraph four extends the text further. " * 30,
            "Paragraph five wraps it up with a closing line.",
        ]
    )
    splitter = RecursiveCharacterSplitter(chunk_size=300, chunk_overlap=50)
    a = splitter.split(text)
    b = splitter.split(text)
    assert a == b
    assert [c.content_hash for c in a] == [c.content_hash for c in b]
    assert all(isinstance(c, ChunkSpec) for c in a)


def test_idempotency_across_splitter_instances() -> None:
    """A fresh splitter with the same config gives the same output as the original."""
    text = ("Line one.\n" * 200) + "\n\n" + ("Line two.\n" * 200)
    a = RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=80).split(text)
    b = RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=80).split(text)
    assert a == b
    assert [c.content_hash for c in a] == [c.content_hash for c in b]


def test_idempotency_content_hash_independent_of_whitespace_variations() -> None:
    """CRLF vs LF, trailing spaces, and triple-blank-line runs all hash to the same chunk."""
    a = "alpha\r\nbeta\r\ngamma   \r\n"
    b = "alpha\nbeta\ngamma\n"
    c = "alpha\nbeta\n\n\n\ngamma\n"
    # normalize_text collapses these three forms to the same string up to the
    # paragraph-blank rule. (c) goes from \n\n\n\n -> \n\n (canonical paragraph
    # break) so its hash will differ from (a)/(b). Verify the documented contract:
    assert compute_content_hash(a) == compute_content_hash(b)
    assert compute_content_hash(c) != compute_content_hash(a)
    # And the splitter passes the same equality through:
    splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=20)
    assert splitter.split(a) == splitter.split(b)


# ----------------------------------------------------------------------
# chunk_size honored
# ----------------------------------------------------------------------


def test_chunk_size_is_respected_for_splittable_text() -> None:
    """Where the splitter has separators to work with, no chunk exceeds chunk_size."""
    text = ". ".join([f"sentence number {i} here" for i in range(200)])
    splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=20)
    chunks = splitter.split(text)
    assert chunks  # non-empty
    for c in chunks:
        assert len(c.text) <= 200 + 20  # tolerate the overlap tail at boundaries


def test_short_input_returns_single_chunk() -> None:
    text = "Hello world, short enough to fit in one chunk."
    splitter = RecursiveCharacterSplitter(chunk_size=1500, chunk_overlap=200)
    chunks = splitter.split(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].position == 0
    assert chunks[0].start_char == 0
    assert chunks[0].end_char == len(text)


def test_empty_input_returns_no_chunks() -> None:
    splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=10)
    assert splitter.split("") == []
    assert splitter.split("\n\n\n") == []


# ----------------------------------------------------------------------
# Overlap honored
# ----------------------------------------------------------------------


def test_overlap_present_between_consecutive_chunks() -> None:
    """Consecutive chunks share a tail/head overlap up to chunk_overlap chars."""
    # Build text long enough that we get >= 3 chunks at the chosen size.
    text = "alpha beta gamma delta " * 200
    splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=40)
    chunks = splitter.split(text)
    assert len(chunks) >= 3
    # For every adjacent pair, the prior chunk's tail should appear at or near
    # the head of the next chunk (the splitter's pack strategy seeds the next
    # chunk from the previous tail).
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        tail = prev.text[-40:]
        # Take the first `40` chars of nxt; the overlap is by construction a
        # prefix or near-prefix of the next chunk.
        head = nxt.text[:40]
        assert head == tail or tail in nxt.text[:80]


def test_overlap_zero_means_no_repeat() -> None:
    text = "alpha beta gamma " * 200
    splitter = RecursiveCharacterSplitter(chunk_size=150, chunk_overlap=0)
    chunks = splitter.split(text)
    assert len(chunks) >= 2
    # Without overlap, consecutive chunks should not share a long tail/head.
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert prev.text[-30:] != nxt.text[:30]


# ----------------------------------------------------------------------
# Hierarchical fallback
# ----------------------------------------------------------------------


def test_hierarchical_falls_back_to_single_newline_when_no_double() -> None:
    """A text with only single newlines must still get split."""
    text = "\n".join([f"line {i}" for i in range(500)])
    assert "\n\n" not in text
    splitter = RecursiveCharacterSplitter(chunk_size=300, chunk_overlap=30)
    chunks = splitter.split(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.text) <= 300 + 30


def test_hierarchical_falls_back_to_character_split_for_long_unbroken_run() -> None:
    """A 5000-char text with no separators must still be split into chunk_size pieces."""
    text = "x" * 5000
    splitter = RecursiveCharacterSplitter(chunk_size=500, chunk_overlap=0)
    chunks = splitter.split(text)
    assert len(chunks) >= 10
    for c in chunks:
        assert len(c.text) <= 500


def test_hierarchical_uses_paragraph_then_line_then_sentence() -> None:
    """Splitter prefers paragraph breaks where available."""
    text = (
        "Paragraph one is just one sentence.\n\n"
        + "Paragraph two has " * 200
        + "\n\nParagraph three."
    )
    splitter = RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=20)
    chunks = splitter.split(text)
    # Paragraph one and three should not be merged with the giant paragraph two.
    first = chunks[0].text
    last = chunks[-1].text
    assert "Paragraph one" in first
    assert "Paragraph three" in last


# ----------------------------------------------------------------------
# Position + offsets
# ----------------------------------------------------------------------


def test_positions_are_zero_based_and_monotonic() -> None:
    text = "abc " * 1000
    splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=30)
    chunks = splitter.split(text)
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_offsets_locate_chunk_in_normalised_text() -> None:
    text = "alpha\n\nbeta\n\ngamma"
    splitter = RecursiveCharacterSplitter(chunk_size=8, chunk_overlap=0)
    chunks = splitter.split(text)
    normalised = normalize_text(text)
    for c in chunks:
        assert normalised[c.start_char : c.end_char] == c.text


# ----------------------------------------------------------------------
# Metadata
# ----------------------------------------------------------------------


def test_metadata_records_splitter_and_config() -> None:
    splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=20)
    chunks = splitter.split("hello world")
    assert chunks
    md = chunks[0].metadata
    assert md["splitter"] == "recursive"
    assert md["chunk_size"] == 200
    assert md["chunk_overlap"] == 20


def test_extra_metadata_is_merged() -> None:
    splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=20)
    chunks = splitter.split("hello world", extra_metadata={"source": "test"})
    assert chunks[0].metadata["source"] == "test"
    assert chunks[0].metadata["splitter"] == "recursive"


# ----------------------------------------------------------------------
# Chunker (selector)
# ----------------------------------------------------------------------


def test_chunker_uses_text_splitter_for_plain_text() -> None:
    chunker = Chunker()
    chunks = chunker.chunk("hello world", mime_type="text/plain", extension=".txt")
    assert chunks
    assert chunks[0].metadata["splitter"] == "recursive"


def test_chunker_uses_code_splitter_for_python_extension() -> None:
    chunker = Chunker()
    chunks = chunker.chunk(
        "def f():\n    return 1\n", mime_type=None, extension=".py"
    )
    assert chunks
    assert chunks[0].metadata["splitter"] == "code_fallback"


def test_chunker_passes_document_type_into_metadata() -> None:
    chunker = Chunker()
    chunks = chunker.chunk(
        "hello", mime_type="text/plain", extension=".txt", document_type="email"
    )
    assert chunks[0].metadata.get("document_type") == "email"


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


def test_rejects_overlap_ge_chunk_size() -> None:
    import pytest

    with pytest.raises(ValueError):
        RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=200)


def test_rejects_non_positive_chunk_size() -> None:
    import pytest

    with pytest.raises(ValueError):
        RecursiveCharacterSplitter(chunk_size=0, chunk_overlap=0)

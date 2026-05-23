"""Stage 5 — quote / near-quote detector.

Per spec §5.2 step 5:

  For every string-typed value (after the Literal whitelist), compute trigram
  shingles. Reject if any string is longer than 64 characters OR if the
  trigram set overlaps >30% with content from the tenant's recent document
  corpus. The corpus query stays inside the tenant.

This stage is a *stub* for v1 — the real corpus shingle store is built in
`M1-MCP-02`. The shingle-overlap signature here is solid; we just inject an
empty corpus by default. The "string too long" half is full.

Injection point: the pipeline takes a `corpus_shingles` callable that returns
the tenant's recent-corpus trigram set. In v1 tests we pass a stub that
returns an empty set. Real callers will pass a function that queries the
tenant's local chunk store.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Optional

from ..schema.observation import ALLOWED_LITERAL_STRINGS
from .results import CheckResult, ReasonCode, Stage


# Per spec: any string longer than 64 chars is suspect by definition because
# our payloads are template-and-bucket-shaped, not narrative.
MAX_STRING_LEN = 64
TRIGRAM_OVERLAP_THRESHOLD = 0.30


CorpusShinglesFn = Callable[[], frozenset[str]]


def _trigrams(value: str) -> set[str]:
    """Return the set of character trigrams in `value` (lowercased)."""

    v = value.lower()
    if len(v) < 3:
        return set()
    return {v[i : i + 3] for i in range(len(v) - 2)}


def _walk_strings(obj: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(obj, str):
        yield (obj, path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")


def _empty_corpus() -> frozenset[str]:
    return frozenset()


def scan_quotes(
    serialized: dict[str, Any],
    corpus_shingles_fn: Optional[CorpusShinglesFn] = None,
) -> CheckResult:
    """Stage 5 verdict. v1: long-string reject + (stubbed) corpus overlap.

    Args:
        serialized: the envelope as a dict.
        corpus_shingles_fn: callable returning the tenant's recent-corpus
            trigram set. In v1 tests, the default empty-corpus stub is
            used. `M1-MCP-02` wires the real query.
    """

    if corpus_shingles_fn is None:
        corpus_shingles_fn = _empty_corpus

    corpus: Optional[frozenset[str]] = None  # lazy load

    for value, json_path in _walk_strings(serialized):
        # Whitelisted controlled-vocabulary values pass.
        if value in ALLOWED_LITERAL_STRINGS:
            continue

        if len(value) > MAX_STRING_LEN:
            return CheckResult(
                stage=Stage.QUOTE_NEAR_QUOTE,
                passed=False,
                reason_code=ReasonCode.STRING_TOO_LONG,
                details=(
                    f"string of length {len(value)} > {MAX_STRING_LEN} at {json_path}"
                ),
            )

        # Corpus overlap. Skipped trivially when the corpus is empty (v1
        # default). Implementation note for M1-MCP-02: callers should
        # pre-compute the trigram set once per ingestion-run for cheap reuse.
        if corpus is None:
            corpus = corpus_shingles_fn()
        if corpus:
            shingles = _trigrams(value)
            if shingles:
                overlap = len(shingles & corpus) / len(shingles)
                if overlap > TRIGRAM_OVERLAP_THRESHOLD:
                    return CheckResult(
                        stage=Stage.QUOTE_NEAR_QUOTE,
                        passed=False,
                        reason_code=ReasonCode.QUOTE_OVERLAP,
                        details=(
                            f"trigram overlap {overlap:.2f} > "
                            f"{TRIGRAM_OVERLAP_THRESHOLD} at {json_path}"
                        ),
                    )

    return CheckResult(stage=Stage.QUOTE_NEAR_QUOTE, passed=True)

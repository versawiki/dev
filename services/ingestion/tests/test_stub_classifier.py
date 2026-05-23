"""StubLLMClassifier — deterministic, no-network classifier used by tests."""

from __future__ import annotations

import pytest

from versawiki_ingestion.classification import ClassifierResult, StubLLMClassifier
from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.parsers.base import ParseResult


def _parsed(full_text: str, **kw) -> ParseResult:
    fields = kw.pop("fields", {})
    return ParseResult(
        document_type="general_document",
        full_text=full_text,
        fields=fields,
        confidence=0.5,
    )


@pytest.mark.asyncio
async def test_stub_picks_top_heuristic_match() -> None:
    taxonomy = Taxonomy.starter()
    stub = StubLLMClassifier()
    doc = _parsed(
        "RFI submitted by Jane; assigned_to structural; question about concrete; response pending.",
        fields={"title": "RFI 042"},
    )

    result = await stub.classify(doc, taxonomy, source_uri="job/rfi_log.txt")

    assert isinstance(result, ClassifierResult)
    assert result.predicted_type == "rfi"
    # Confidence equals the heuristic score for the picked type.
    expected = taxonomy.match_score(doc, "rfi", source_uri="job/rfi_log.txt")
    assert result.confidence == pytest.approx(expected)
    # Stub does not set uncertainty_reason — the orchestrator does that.
    assert result.uncertainty_reason is None


@pytest.mark.asyncio
async def test_stub_alternatives_are_next_three_by_heuristic_desc() -> None:
    taxonomy = Taxonomy.starter()
    stub = StubLLMClassifier()
    doc = _parsed("RFI submitted; concrete mix; response pending.")

    result = await stub.classify(doc, taxonomy, source_uri="rfi_042.txt")

    # Up to 3 alternatives, sorted descending. None equals predicted_type.
    assert len(result.alternatives) <= 3
    assert all(a.type != result.predicted_type for a in result.alternatives)
    confidences = [a.confidence for a in result.alternatives]
    assert confidences == sorted(confidences, reverse=True)


@pytest.mark.asyncio
async def test_stub_is_deterministic() -> None:
    taxonomy = Taxonomy.starter()
    stub = StubLLMClassifier()
    doc = _parsed("Some unstructured text without obvious type cues.")

    a = await stub.classify(doc, taxonomy)
    b = await stub.classify(doc, taxonomy)

    assert a == b


@pytest.mark.asyncio
async def test_stub_returns_default_type_on_blank_text() -> None:
    taxonomy = Taxonomy.starter()
    stub = StubLLMClassifier()
    doc = _parsed("")

    result = await stub.classify(doc, taxonomy)

    # No signal at all -> top match falls back to taxonomy.default_type
    # (or whichever type tied at zero — but the predicted name should exist).
    assert result.predicted_type in taxonomy
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_stub_signals_empty_dict() -> None:
    """Stub leaves signals to the orchestrator — its own dict is empty."""
    taxonomy = Taxonomy.starter()
    stub = StubLLMClassifier()
    doc = _parsed("RFI 042 about concrete.")
    result = await stub.classify(doc, taxonomy)
    assert result.signals == {}


def test_provider_name() -> None:
    assert StubLLMClassifier().provider_name == "stub"

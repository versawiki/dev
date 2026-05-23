"""DocumentClassifier orchestration — LLM + heuristic cross-check."""

from __future__ import annotations

import pytest

from versawiki_ingestion.classification import (
    AnthropicClassifier,
    ClassifierResult,
    DocumentClassifier,
    StubLLMClassifier,
)
from versawiki_ingestion.classification.base import Alternative
from versawiki_ingestion.classification.classifier import ClassifierThresholds
from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.parsers.base import ParseResult


def _parsed(text: str, fields: dict | None = None) -> ParseResult:
    return ParseResult(
        document_type="general_document",
        full_text=text,
        fields=fields or {},
        confidence=0.5,
    )


class _ScriptedLLM:
    """A pretend LLM provider that returns a fixed ClassifierResult.

    Used to test orchestration paths where we want to control the LLM's
    output exactly (e.g. simulate the LLM disagreeing with the heuristic).
    """

    provider_name = "scripted"

    def __init__(self, result: ClassifierResult) -> None:
        self._result = result

    async def classify(
        self,
        parsed_doc: ParseResult,
        taxonomy: Taxonomy,
        *,
        source_uri: str = "",
    ) -> ClassifierResult:
        return self._result


# ----------------------------------------------------------------------
# Agreement path — high confidence, no uncertainty reason
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_high_confidence_when_llm_and_heuristic_agree() -> None:
    taxonomy = Taxonomy.starter()
    # LLM agrees with the heuristic top match.
    scripted = _ScriptedLLM(
        ClassifierResult(
            predicted_type="rfi",
            confidence=0.95,
            alternatives=[Alternative(type="letter", confidence=0.2)],
            uncertainty_reason=None,
            signals={},
            rationale="agreement",
        )
    )
    classifier = DocumentClassifier(scripted, taxonomy=taxonomy)
    doc = _parsed(
        "RFI submitted by Jane; assigned_to structural team; question about concrete; response pending.",
        fields={"title": "RFI 042"},
    )
    result = await classifier.classify(doc, source_uri="job/rfi_042.txt")
    assert result.predicted_type == "rfi"
    assert result.uncertainty_reason is None
    assert result.confidence >= 0.55  # above LOW_CONFIDENCE threshold
    # Signals are present and bounded.
    assert "header_match_score" in result.signals
    assert "keyword_density" in result.signals
    assert "structural_complexity" in result.signals
    assert "llm_confidence" in result.signals
    assert "heuristic_agreement" in result.signals
    assert 0.0 <= result.signals["heuristic_agreement"] <= 1.0


# ----------------------------------------------------------------------
# Disagreement -> TIE_BETWEEN_TYPES + confidence drop
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_disagrees_with_heuristic_drops_confidence_and_flags_tie() -> None:
    taxonomy = Taxonomy.starter()
    # Doc reads strongly like an RFI, but the LLM (wrongly) picks "letter".
    scripted = _ScriptedLLM(
        ClassifierResult(
            predicted_type="letter",
            confidence=0.85,
            alternatives=[Alternative(type="rfi", confidence=0.3)],
            uncertainty_reason=None,
            signals={},
            rationale="picked letter",
        )
    )
    classifier = DocumentClassifier(scripted, taxonomy=taxonomy)
    doc = _parsed(
        "RFI submitted by Jane; assigned_to structural team; question about concrete; response pending.",
        fields={"title": "RFI 042"},
    )
    result = await classifier.classify(doc, source_uri="job/rfi_042.txt")
    assert result.predicted_type == "letter"
    # Confidence dropped from 0.85 because of disagreement.
    assert result.confidence < 0.85
    assert result.uncertainty_reason in {"TIE_BETWEEN_TYPES", "NOVEL_PATTERN", "LOW_CONFIDENCE"}


# ----------------------------------------------------------------------
# Novel pattern: LLM picks a type the heuristic doesn't see at all
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_novel_pattern_when_llm_picks_type_with_zero_heuristic() -> None:
    taxonomy = Taxonomy.starter()
    # Doc reads strongly like an RFI; LLM picks "design_calculation" which
    # has effectively no signal in the text.
    scripted = _ScriptedLLM(
        ClassifierResult(
            predicted_type="design_calculation",
            confidence=0.7,
            alternatives=[],
            uncertainty_reason=None,
            signals={},
            rationale="picked calc",
        )
    )
    classifier = DocumentClassifier(scripted, taxonomy=taxonomy)
    doc = _parsed(
        "RFI submitted by Jane; assigned_to structural team; question about concrete; response pending.",
        fields={"title": "RFI 042"},
    )
    result = await classifier.classify(doc, source_uri="job/rfi_042.txt")
    assert result.uncertainty_reason in {"NOVEL_PATTERN", "TIE_BETWEEN_TYPES"}
    assert result.confidence < 0.7


# ----------------------------------------------------------------------
# LOW_CONFIDENCE
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_confidence_flag_when_llm_score_is_low() -> None:
    taxonomy = Taxonomy.starter()
    scripted = _ScriptedLLM(
        ClassifierResult(
            predicted_type="rfi",
            confidence=0.30,
            alternatives=[],
            uncertainty_reason=None,
            signals={},
            rationale="unsure",
        )
    )
    classifier = DocumentClassifier(scripted, taxonomy=taxonomy)
    doc = _parsed(
        "RFI submitted by Jane; assigned_to structural team.",
        fields={"title": "RFI 042"},
    )
    result = await classifier.classify(doc, source_uri="rfi_042.txt")
    assert result.uncertainty_reason == "LOW_CONFIDENCE"


# ----------------------------------------------------------------------
# Alternatives sorted descending
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alternatives_sorted_by_confidence_descending() -> None:
    taxonomy = Taxonomy.starter()
    scripted = _ScriptedLLM(
        ClassifierResult(
            predicted_type="rfi",
            confidence=0.9,
            alternatives=[
                Alternative(type="letter", confidence=0.1),
                Alternative(type="submittal", confidence=0.4),
            ],
            uncertainty_reason=None,
            signals={},
            rationale="r",
        )
    )
    classifier = DocumentClassifier(scripted, taxonomy=taxonomy)
    doc = _parsed("RFI submitted by Jane; question about concrete.")
    result = await classifier.classify(doc, source_uri="rfi_042.txt")
    confidences = [a.confidence for a in result.alternatives]
    assert confidences == sorted(confidences, reverse=True)
    # Predicted type is never in alternatives.
    assert all(a.type != "rfi" for a in result.alternatives)


# ----------------------------------------------------------------------
# Stub LLM end-to-end through the orchestrator
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_with_stub_llm_is_deterministic() -> None:
    taxonomy = Taxonomy.starter()
    classifier = DocumentClassifier(StubLLMClassifier(), taxonomy=taxonomy)
    doc = _parsed("RFI 042 about concrete mix design; assigned_to structural team.")
    a = await classifier.classify(doc, source_uri="rfi_042.txt")
    b = await classifier.classify(doc, source_uri="rfi_042.txt")
    assert a == b


# ----------------------------------------------------------------------
# LLM-provider error short-circuit
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_novel_pattern_short_circuits_to_novel_pattern() -> None:
    """If the LLM provider already says NOVEL_PATTERN (e.g. HTTP error),
    the orchestrator must keep that reason and augment signals."""
    taxonomy = Taxonomy.starter()
    scripted = _ScriptedLLM(
        ClassifierResult(
            predicted_type="unclassified",
            confidence=0.0,
            alternatives=[],
            uncertainty_reason="NOVEL_PATTERN",
            signals={"llm_error": 1.0},
            rationale="llm-error",
        )
    )
    classifier = DocumentClassifier(scripted, taxonomy=taxonomy)
    doc = _parsed("RFI 042")
    result = await classifier.classify(doc, source_uri="rfi_042.txt")
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    assert result.signals["llm_error"] == 1.0
    assert "header_match_score" in result.signals  # orchestrator added them


# ----------------------------------------------------------------------
# Defaults: classifier without args still works
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_construction_uses_stub_and_starter_taxonomy() -> None:
    classifier = DocumentClassifier()
    doc = _parsed("RFI 042 about concrete.")
    result = await classifier.classify(doc, source_uri="rfi_042.txt")
    assert result.predicted_type in classifier.taxonomy
    assert isinstance(result.signals, dict)


# ----------------------------------------------------------------------
# Thresholds knob
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thresholds_can_be_tightened() -> None:
    """Bumping the low-confidence threshold to 0.99 should flag everything."""
    taxonomy = Taxonomy.starter()
    scripted = _ScriptedLLM(
        ClassifierResult(
            predicted_type="rfi",
            confidence=0.9,
            alternatives=[],
            uncertainty_reason=None,
            signals={},
            rationale="r",
        )
    )
    classifier = DocumentClassifier(
        scripted,
        taxonomy=taxonomy,
        thresholds=ClassifierThresholds(low_confidence=0.99),
    )
    doc = _parsed("RFI 042 about concrete.", fields={"title": "RFI 042"})
    result = await classifier.classify(doc, source_uri="rfi_042.txt")
    assert result.uncertainty_reason == "LOW_CONFIDENCE"


# ----------------------------------------------------------------------
# Sanity on AnthropicClassifier instance shape
# ----------------------------------------------------------------------


def test_anthropic_classifier_is_an_llm_provider() -> None:
    from versawiki_ingestion.classification.llm_provider import LLMClassifierProvider
    inst = AnthropicClassifier(api_key="x")
    assert isinstance(inst, LLMClassifierProvider)

"""`DocumentClassifier` — orchestrates heuristic + LLM with cross-check.

Flow per document:

  1. Compute heuristic match scores for every taxonomy type.
  2. Call the LLM provider (Anthropic / OpenAI / Stub) for its pick.
  3. Cross-check:
       - If the LLM's pick agrees with the top heuristic match, keep the
         LLM's confidence verbatim (but interpolated up by the heuristic
         agreement signal).
       - If the LLM's pick is the heuristic's #2 with a small gap,
         flag `uncertainty_reason="TIE_BETWEEN_TYPES"` and drop confidence
         by the disagreement gap.
       - If the LLM picked a type that scored ~0 in the heuristic,
         flag `uncertainty_reason="NOVEL_PATTERN"`.
       - If everything is fine but confidence ends up below
         `low_confidence_threshold`, flag `uncertainty_reason="LOW_CONFIDENCE"`.
  4. Populate the `signals` dict with interpretable features the meta-MCP's
     `compute_classifier_uncertainty()` can aggregate.

Why this rather than trusting the LLM outright: the prior-art audit (M0-06)
showed that the previous MCP under-classified by dumping everything into
`general_document` whenever the LLM hesitated. We want the *hesitation* to
become a signal, not silently flatten the taxonomy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..parsers.base import ParseResult
from .base import Alternative, ClassifierResult, UncertaintyReason
from .llm_provider import LLMClassifierProvider, StubLLMClassifier
from .taxonomy import Taxonomy


# Threshold defaults — tuned by the meta-MCP later via skill writes. M1
# defaults below are reasonable starting points.

DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_DISAGREEMENT_GAP = 0.25  # |llm_heuristic - top_heuristic|
DEFAULT_NOVEL_PATTERN_HEURISTIC = 0.05
DEFAULT_TIE_GAP = 0.10  # if top-2 heuristic types are within this, it's a tie


@dataclass(frozen=True)
class ClassifierThresholds:
    """Thresholds that govern uncertainty-reason assignment."""

    low_confidence: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD
    disagreement_gap: float = DEFAULT_DISAGREEMENT_GAP
    novel_pattern_heuristic: float = DEFAULT_NOVEL_PATTERN_HEURISTIC
    tie_gap: float = DEFAULT_TIE_GAP


class DocumentClassifier:
    """Pipeline-side orchestrator. Stateless given an LLM provider + taxonomy."""

    def __init__(
        self,
        llm: Optional[LLMClassifierProvider] = None,
        *,
        taxonomy: Optional[Taxonomy] = None,
        thresholds: Optional[ClassifierThresholds] = None,
    ) -> None:
        self.llm = llm or StubLLMClassifier()
        self.taxonomy = taxonomy or Taxonomy.starter()
        self.thresholds = thresholds or ClassifierThresholds()

    async def classify(
        self,
        parsed_doc: ParseResult,
        *,
        source_uri: str = "",
    ) -> ClassifierResult:
        """Return a `ClassifierResult` for the parsed document.

        Deterministic given a deterministic LLM (e.g. `StubLLMClassifier`).
        """
        heuristic_scores = self.taxonomy.score_all(parsed_doc, source_uri=source_uri)
        top_heuristic_name, top_heuristic_score = self.taxonomy.best_match(
            parsed_doc, source_uri=source_uri
        )
        second_heuristic_score = _second_highest(heuristic_scores)

        llm_result = await self.llm.classify(
            parsed_doc, self.taxonomy, source_uri=source_uri
        )

        return self._adjudicate(
            llm_result,
            heuristic_scores=heuristic_scores,
            top_heuristic_name=top_heuristic_name,
            top_heuristic_score=top_heuristic_score,
            second_heuristic_score=second_heuristic_score,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _adjudicate(
        self,
        llm_result: ClassifierResult,
        *,
        heuristic_scores: dict[str, float],
        top_heuristic_name: str,
        top_heuristic_score: float,
        second_heuristic_score: float,
    ) -> ClassifierResult:
        """Combine LLM + heuristic into the final `ClassifierResult`.

        Honors a pre-existing `uncertainty_reason` from the LLM provider's
        error fallback (NOVEL_PATTERN) by short-circuiting the cross-check.
        """
        thr = self.thresholds

        # Provider-side error fallback short-circuits adjudication —
        # signals get augmented but the verdict stays NOVEL_PATTERN.
        if llm_result.uncertainty_reason == "NOVEL_PATTERN":
            signals = dict(llm_result.signals)
            signals.setdefault("llm_error", 1.0)
            signals.setdefault("header_match_score", _clamp01(top_heuristic_score))
            signals.setdefault("heuristic_agreement", 0.0)
            return llm_result.model_copy(update={"signals": signals})

        predicted = llm_result.predicted_type
        llm_score = float(llm_result.confidence)
        llm_heuristic_score = float(heuristic_scores.get(predicted, 0.0))
        gap_to_top = max(0.0, top_heuristic_score - llm_heuristic_score)

        # Build alternatives list — combine LLM's alternatives with
        # heuristic-top alternatives, deduped, sorted by confidence desc.
        alts = _merge_alternatives(
            llm_result.alternatives,
            heuristic_scores,
            predicted_type=predicted,
            limit=3,
        )

        # Decide uncertainty_reason in priority order.
        reason: Optional[UncertaintyReason] = None
        adjusted_confidence = llm_score

        if (
            top_heuristic_score >= thr.novel_pattern_heuristic
            and llm_heuristic_score < thr.novel_pattern_heuristic
            and gap_to_top >= thr.disagreement_gap
        ):
            # LLM picked something the heuristic doesn't see at all and
            # there's a meaningful alternative. Treat as a novel pattern.
            reason = "NOVEL_PATTERN"
            adjusted_confidence = max(0.0, llm_score - gap_to_top)
        elif (
            predicted != top_heuristic_name
            and gap_to_top >= thr.disagreement_gap
        ):
            # Hard disagreement: heuristic's #1 is a different type and the
            # gap is large. Flag as TIE_BETWEEN_TYPES and discount.
            reason = "TIE_BETWEEN_TYPES"
            adjusted_confidence = max(0.0, llm_score - gap_to_top)
        elif (
            top_heuristic_score > 0.0
            and second_heuristic_score > 0.0
            and (top_heuristic_score - second_heuristic_score) < thr.tie_gap
            and llm_score < (thr.low_confidence + 0.15)
        ):
            # The heuristic itself is split and the LLM isn't very sure.
            reason = "TIE_BETWEEN_TYPES"

        if reason is None and adjusted_confidence < thr.low_confidence:
            reason = "LOW_CONFIDENCE"

        signals = _build_signals(
            top_heuristic_score=top_heuristic_score,
            llm_heuristic_score=llm_heuristic_score,
            second_heuristic_score=second_heuristic_score,
            llm_confidence=llm_score,
            llm_alternatives=llm_result.alternatives,
        )

        return ClassifierResult(
            predicted_type=predicted,
            confidence=_clamp01(adjusted_confidence),
            alternatives=alts,
            uncertainty_reason=reason,
            signals=signals,
            rationale=llm_result.rationale,
        )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _second_highest(scores: dict[str, float]) -> float:
    if len(scores) < 2:
        return 0.0
    ranked = sorted(scores.values(), reverse=True)
    return float(ranked[1])


def _merge_alternatives(
    llm_alts: list[Alternative],
    heuristic_scores: dict[str, float],
    *,
    predicted_type: str,
    limit: int,
) -> list[Alternative]:
    """Combine LLM-listed and heuristic-ranked alternatives, top-`limit`."""
    candidates: dict[str, float] = {}
    for alt in llm_alts:
        if alt.type == predicted_type:
            continue
        candidates[alt.type] = max(candidates.get(alt.type, 0.0), alt.confidence)
    # Layer in heuristic-ranked alternatives — they may add types the LLM
    # didn't list. We add them at their heuristic score so the meta-MCP
    # confusion-pair stream sees the broader picture.
    for name, score in heuristic_scores.items():
        if name == predicted_type or score <= 0.0:
            continue
        candidates[name] = max(candidates.get(name, 0.0), score)

    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))
    return [Alternative(type=name, confidence=_clamp01(score)) for name, score in ranked[:limit]]


def _build_signals(
    *,
    top_heuristic_score: float,
    llm_heuristic_score: float,
    second_heuristic_score: float,
    llm_confidence: float,
    llm_alternatives: list[Alternative],
) -> dict[str, float]:
    """Build the bounded-vocabulary signals dict.

    Vocabulary (stable — the meta-MCP signature function reads these names):

      * `header_match_score`: heuristic score of the LLM's predicted type.
        Proxies how strongly the document looks like the chosen type from
        filename + extracted fields alone.
      * `keyword_density`: heuristic score of the *top* heuristic candidate,
        regardless of whether the LLM picked it. Useful for the meta-MCP to
        spot "the document looks like X but the LLM keeps saying Y."
      * `structural_complexity`: 1 - 1/(1+N) where N is the count of non-
        zero heuristic alternatives. High when many types could plausibly
        apply; low when only one type even looks plausible.
      * `llm_confidence`: the raw LLM-reported confidence, before adjustment.
      * `heuristic_agreement`: 1.0 if the LLM picked the top heuristic
        candidate, else (1 - gap_to_top), floored at 0.
      * `alt_count`: |alts|/3, capped at 1.0. Helps spot LLMs that habitually
        decline to suggest alternatives.
    """
    gap_to_top = max(0.0, top_heuristic_score - llm_heuristic_score)
    structural = 1.0 - 1.0 / (1.0 + max(0, _nonzero_count(top_heuristic_score, second_heuristic_score)))

    return {
        "header_match_score": _clamp01(llm_heuristic_score),
        "keyword_density": _clamp01(top_heuristic_score),
        "structural_complexity": _clamp01(structural),
        "llm_confidence": _clamp01(llm_confidence),
        "heuristic_agreement": _clamp01(1.0 - gap_to_top),
        "alt_count": _clamp01(len(llm_alternatives) / 3.0),
    }


def _nonzero_count(*scores: float) -> int:
    return sum(1 for s in scores if s and s > 0.0 and not math.isnan(s))


def _clamp01(x: float) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)

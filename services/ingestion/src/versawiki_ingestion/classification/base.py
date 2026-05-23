"""`ClassifierResult` — the contract every classifier emits.

The result populates the fields the meta-MCP's `RawClassifierUncertaintyEvent`
expects when it samples per-document classifier output:

- `confidence` -> `overall_confidences[i]`
- `predicted_type` + the top `alternatives[0].type` -> one `uncertain_pair`
  observation when `uncertainty_reason` is set
- `signals` -> interpretable per-document features the meta-MCP's signature
  function can aggregate without ever touching content

`uncertainty_reason` is the human-readable trigger for the meta-MCP skill-write
loop. ``None`` means "we're confident"; any non-None value means the document
should be sampled into the uncertainty stream.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

UncertaintyReason = Literal["LOW_CONFIDENCE", "TIE_BETWEEN_TYPES", "NOVEL_PATTERN"]


class Alternative(BaseModel):
    """One alternative type the classifier considered, with its confidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ClassifierResult(BaseModel):
    """The classifier's verdict on a single parsed document.

    Every field is populated on success and on failure — when the LLM call
    errors, the orchestrator returns a result with `confidence=0.0` and
    `uncertainty_reason="NOVEL_PATTERN"` rather than raising.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    predicted_type: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    # Top-3 next-best types, sorted by confidence descending. May be empty
    # (e.g. a taxonomy with only one type, or all alternatives at zero score).
    alternatives: list[Alternative] = Field(default_factory=list)
    uncertainty_reason: Optional[UncertaintyReason] = Field(default=None)
    # Interpretable, bounded-vocabulary features. The meta-MCP signature
    # function reads these — keep the keys stable. Values are floats in [0,1]
    # by convention; the validator enforces that.
    signals: dict[str, float] = Field(default_factory=dict)
    # Optional free-text from the LLM, kept tenant-side only (never crosses
    # to the meta-MCP). Useful for tenant-local debugging.
    rationale: str = Field(default="")

    def model_post_init(self, _ctx: object) -> None:  # noqa: D401 — pydantic hook
        # Bound-check signal values without changing them (downstream
        # compute_classifier_uncertainty expects a uniform [0,1] vocabulary).
        for key, value in self.signals.items():
            if not isinstance(value, (int, float)):
                raise ValueError(f"signal {key!r} must be numeric, got {type(value).__name__}")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"signal {key!r} = {value} is outside [0,1]")

        # Alternatives must be sorted by confidence descending. If we accept
        # arbitrary input we silently re-sort to make downstream code simpler.
        if self.alternatives:
            sorted_alts = sorted(self.alternatives, key=lambda a: a.confidence, reverse=True)
            if [a.confidence for a in sorted_alts] != [a.confidence for a in self.alternatives]:
                # Pydantic v2 frozen — we re-assign through __dict__ because
                # this is the model's own __init__ hook.
                object.__setattr__(self, "alternatives", sorted_alts)

    @property
    def is_uncertain(self) -> bool:
        """Quick predicate for the meta-MCP sampler."""
        return self.uncertainty_reason is not None

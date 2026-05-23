"""Document classification — LLM-driven type assignment with uncertainty signals.

Layout:

- `base.py` — `ClassifierResult` Pydantic model (the contract the chunker and
  the meta-MCP both consume).
- `taxonomy.py` — loader for `seeds/aec_starter_taxonomy.yaml` plus per-tenant
  overrides and a cheap heuristic match scorer.
- `llm_provider.py` — `LLMClassifierProvider` Protocol and three implementations
  (Anthropic primary, OpenAI fallback, Stub for tests).
- `classifier.py` — `DocumentClassifier`: orchestrates heuristic + LLM and
  cross-checks the two for disagreement.
- `prompts.py` — the (single, reviewable) system + user prompt templates.

The `ClassifierResult` flowing out of this package is what becomes the
`RawClassifierUncertaintyEvent` consumed by the meta-MCP collector. Keep the
`signals` dict's keys stable — the meta-MCP signature function reads them.
"""

from .base import ClassifierResult, UncertaintyReason
from .classifier import DocumentClassifier
from .llm_provider import (
    AnthropicClassifier,
    LLMClassifierProvider,
    OpenAIClassifier,
    StubLLMClassifier,
)
from .taxonomy import Taxonomy, TaxonomyType

__all__ = [
    "AnthropicClassifier",
    "ClassifierResult",
    "DocumentClassifier",
    "LLMClassifierProvider",
    "OpenAIClassifier",
    "StubLLMClassifier",
    "Taxonomy",
    "TaxonomyType",
    "UncertaintyReason",
]

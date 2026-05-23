"""LLM classifier providers.

This module provides the `LLMClassifierProvider` Protocol plus three
implementations:

- `AnthropicClassifier` — primary (per DECISIONS.md 2026-05-22 stack lock).
- `OpenAIClassifier` — secondary fallback.
- `StubLLMClassifier` — deterministic, no-network classifier used by tests
  and as the default in CI. Picks the type with the highest heuristic match
  score and reports `confidence = heuristic_score`.

The HTTP providers parse the LLM's JSON response, clamp `confidence` to
[0,1], drop any `alternatives` entries that aren't in the taxonomy, and
fall back to a low-confidence `unclassified` result on any error or
malformed response. The orchestrator (`DocumentClassifier`) does the final
heuristic cross-check and uncertainty-reason assignment.

Tests never make real network calls — they either use `StubLLMClassifier`
directly or inject a fake `httpx.AsyncClient` into the HTTP providers.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Optional, Protocol, runtime_checkable

import httpx

from ..parsers.base import ParseResult
from .base import Alternative, ClassifierResult
from .prompts import SYSTEM_PROMPT, render_user_prompt
from .taxonomy import Taxonomy


# ----------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------


@runtime_checkable
class LLMClassifierProvider(Protocol):
    """A provider that, given a parsed doc and a taxonomy, returns the LLM's
    best-guess `ClassifierResult`.

    The orchestrator may overwrite `confidence` and `uncertainty_reason`
    based on the heuristic cross-check — provider implementations should
    just return what the LLM said, plus any error-degraded fallback.
    """

    provider_name: str

    async def classify(
        self,
        parsed_doc: ParseResult,
        taxonomy: Taxonomy,
        *,
        source_uri: str = "",
    ) -> ClassifierResult: ...


# ----------------------------------------------------------------------
# Stub — deterministic, no network. Default in tests and CI.
# ----------------------------------------------------------------------


class StubLLMClassifier:
    """Deterministic classifier — picks the top heuristic match.

    Confidence is set to the heuristic score. Alternatives are the next-3
    types ranked by heuristic score. Signals are empty (the orchestrator
    layers its own signals on top).

    This is what makes the pipeline deterministic for the chunker-idempotency
    contract in `test_pipeline_process_document.py`.
    """

    provider_name = "stub"

    async def classify(
        self,
        parsed_doc: ParseResult,
        taxonomy: Taxonomy,
        *,
        source_uri: str = "",
    ) -> ClassifierResult:
        scores = taxonomy.score_all(parsed_doc, source_uri=source_uri)
        if not scores:
            return ClassifierResult(
                predicted_type=taxonomy.unclassified_type,
                confidence=0.0,
                alternatives=[],
                uncertainty_reason="NOVEL_PATTERN",
                signals={},
                rationale="empty taxonomy",
            )

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        predicted_type, predicted_score = ranked[0]
        alts = [
            Alternative(type=name, confidence=score)
            for name, score in ranked[1:4]
        ]
        return ClassifierResult(
            predicted_type=predicted_type,
            confidence=float(predicted_score),
            alternatives=alts,
            uncertainty_reason=None,
            signals={},
            rationale="stub: top heuristic match",
        )


# ----------------------------------------------------------------------
# Anthropic — primary provider
# ----------------------------------------------------------------------


ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 600
DEFAULT_TIMEOUT_S = 30.0


class AnthropicClassifier:
    """Calls the Anthropic Messages API to classify a parsed document.

    Uses the system prompt verbatim and renders the user prompt with the
    taxonomy + doc excerpt. Errors degrade to `confidence=0.0,
    uncertainty_reason="NOVEL_PATTERN"` rather than raising — the meta-MCP
    skill-write loop is the recovery path, not a re-raise.
    """

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        model: str = ANTHROPIC_DEFAULT_MODEL,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self._sleep = sleep  # reserved for retry; kept for API symmetry

    async def classify(
        self,
        parsed_doc: ParseResult,
        taxonomy: Taxonomy,
        *,
        source_uri: str = "",
    ) -> ClassifierResult:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            user_prompt = render_user_prompt(
                parsed_doc,
                [(t.name, t.description) for t in taxonomy.list_types()],
                source_uri=source_uri,
            )
            payload = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            headers = {
                "x-api-key": self._resolve_api_key(),
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            }
            try:
                resp = await client.post(ANTHROPIC_MESSAGES_URL, json=payload, headers=headers)
            except httpx.HTTPError as e:
                return _error_result(taxonomy, f"http error: {e}")
            if resp.status_code != 200:
                return _error_result(taxonomy, f"http {resp.status_code}")
            body = resp.json()
            text = _extract_anthropic_text(body)
            return _parse_llm_json(text, taxonomy)
        except Exception as e:  # noqa: BLE001 — outer safety net
            return _error_result(taxonomy, f"unhandled: {e}")
        finally:
            if self._owns_client:
                await client.aclose()

    def _resolve_api_key(self) -> str:
        key = self._api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "AnthropicClassifier: ANTHROPIC_API_KEY is not set. "
                "Set the env var or pass api_key=... to the provider."
            )
        return key


# ----------------------------------------------------------------------
# OpenAI — secondary fallback provider
# ----------------------------------------------------------------------


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIClassifier:
    """OpenAI chat-completions fallback for document classification."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        model: str = OPENAI_DEFAULT_MODEL,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self._sleep = sleep

    async def classify(
        self,
        parsed_doc: ParseResult,
        taxonomy: Taxonomy,
        *,
        source_uri: str = "",
    ) -> ClassifierResult:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            user_prompt = render_user_prompt(
                parsed_doc,
                [(t.name, t.description) for t in taxonomy.list_types()],
                source_uri=source_uri,
            )
            payload = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            }
            headers = {
                "Authorization": f"Bearer {self._resolve_api_key()}",
                "Content-Type": "application/json",
            }
            try:
                resp = await client.post(OPENAI_CHAT_URL, json=payload, headers=headers)
            except httpx.HTTPError as e:
                return _error_result(taxonomy, f"http error: {e}")
            if resp.status_code != 200:
                return _error_result(taxonomy, f"http {resp.status_code}")
            body = resp.json()
            text = _extract_openai_text(body)
            return _parse_llm_json(text, taxonomy)
        except Exception as e:  # noqa: BLE001
            return _error_result(taxonomy, f"unhandled: {e}")
        finally:
            if self._owns_client:
                await client.aclose()

    def _resolve_api_key(self) -> str:
        key = self._api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAIClassifier: OPENAI_API_KEY is not set. "
                "Set the env var or pass api_key=... to the provider."
            )
        return key


# ----------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------


def _extract_anthropic_text(body: dict[str, Any]) -> str:
    """Pull the assistant text out of an Anthropic /v1/messages response."""
    content = body.get("content", []) or []
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _extract_openai_text(body: dict[str, Any]) -> str:
    choices = body.get("choices", []) or []
    if not choices:
        return ""
    first = choices[0] or {}
    msg = first.get("message", {}) or {}
    return str(msg.get("content", ""))


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(text: str, taxonomy: Taxonomy) -> ClassifierResult:
    """Parse the LLM's JSON response into a `ClassifierResult`.

    Robust to:
      * Surrounding prose (we extract the first {...} blob).
      * Out-of-range confidence (clamped).
      * Type names not in the taxonomy (mapped to `unclassified`).
      * Missing `alternatives` (defaulted to []).
    """
    if not text:
        return _error_result(taxonomy, "empty LLM response")

    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return _error_result(taxonomy, "no JSON object in LLM response")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return _error_result(taxonomy, f"json parse error: {e}")

    if not isinstance(data, dict):
        return _error_result(taxonomy, "LLM response was not an object")

    predicted_type = str(data.get("predicted_type", "")).strip()
    if predicted_type not in taxonomy:
        # Map unknown types to the taxonomy's unclassified bucket; the
        # orchestrator will set `uncertainty_reason="NOVEL_PATTERN"`.
        predicted_type = taxonomy.unclassified_type if taxonomy.unclassified_type in taxonomy else taxonomy.default_type
        # If even those are missing, fall back to the first listed type.
        if predicted_type not in taxonomy:
            predicted_type = next(iter(taxonomy.type_names()))

    confidence = _clamp01(data.get("confidence", 0.0))

    alts_raw = data.get("alternatives", []) or []
    alts: list[Alternative] = []
    if isinstance(alts_raw, list):
        for entry in alts_raw[:3]:
            if not isinstance(entry, dict):
                continue
            t = str(entry.get("type", "")).strip()
            c = _clamp01(entry.get("confidence", 0.0))
            if t and t != predicted_type and t in taxonomy:
                alts.append(Alternative(type=t, confidence=c))

    rationale = str(data.get("rationale", "")).strip()

    return ClassifierResult(
        predicted_type=predicted_type,
        confidence=confidence,
        alternatives=alts,
        uncertainty_reason=None,
        signals={},
        rationale=rationale,
    )


def _error_result(taxonomy: Taxonomy, reason: str) -> ClassifierResult:
    """Build a degraded result for an LLM call that failed or was malformed."""
    fallback_type = (
        taxonomy.unclassified_type
        if taxonomy.unclassified_type in taxonomy
        else (
            taxonomy.default_type
            if taxonomy.default_type in taxonomy
            else next(iter(taxonomy.type_names()))
        )
    )
    return ClassifierResult(
        predicted_type=fallback_type,
        confidence=0.0,
        alternatives=[],
        uncertainty_reason="NOVEL_PATTERN",
        signals={"llm_error": 1.0},
        rationale=f"llm-error: {reason}",
    )


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v

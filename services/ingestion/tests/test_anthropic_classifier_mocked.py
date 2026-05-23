"""AnthropicClassifier tests — fully mocked, no network.

Uses a fake `httpx.AsyncClient` to script responses, mirroring the pattern
in `test_embedding_openai.py`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from versawiki_ingestion.classification import AnthropicClassifier
from versawiki_ingestion.classification.llm_provider import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_MESSAGES_URL,
)
from versawiki_ingestion.classification.prompts import SYSTEM_PROMPT
from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.parsers.base import ParseResult


# ----------------------------------------------------------------------
# Fake httpx client (same pattern as test_embedding_openai.py)
# ----------------------------------------------------------------------


async def _noop_sleep(_s: float) -> None:
    return None


class FakeAsyncClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError("FakeAsyncClient ran out of scripted responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        status, body = item
        return _make_response(status, body)

    async def aclose(self) -> None:
        return None


def _make_response(status: int, body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status_code=status, content=json.dumps(body).encode("utf-8"))


def _anthropic_ok(predicted_type: str, confidence: float, alts: list[dict] | None = None, rationale: str = "") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "predicted_type": predicted_type,
                        "confidence": confidence,
                        "alternatives": alts or [],
                        "rationale": rationale,
                    }
                ),
            }
        ],
        "model": "claude-sonnet-4-5",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 30},
    }


def _parsed(text: str = "RFI 042 question about concrete mix design.") -> ParseResult:
    return ParseResult(
        document_type="general_document",
        full_text=text,
        fields={"title": "RFI 042"},
        confidence=0.6,
    )


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sends_system_prompt_verbatim_and_correct_url() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient([(200, _anthropic_ok("rfi", 0.92))])
    classifier = AnthropicClassifier(api_key="sk-test", client=client)

    result = await classifier.classify(_parsed(), taxonomy, source_uri="rfi_042.txt")

    assert result.predicted_type == "rfi"
    assert result.confidence == 0.92
    # One HTTP call.
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == ANTHROPIC_MESSAGES_URL
    # System prompt is sent verbatim.
    assert call["json"]["system"] == SYSTEM_PROMPT
    assert call["headers"]["x-api-key"] == "sk-test"
    assert call["headers"]["anthropic-version"] == ANTHROPIC_API_VERSION
    # User message contains the taxonomy types and the source URI.
    user_text = call["json"]["messages"][0]["content"]
    assert "rfi:" in user_text
    assert "rfi_042.txt" in user_text


@pytest.mark.asyncio
async def test_parses_alternatives_and_drops_unknown_types() -> None:
    taxonomy = Taxonomy.starter()
    body = _anthropic_ok(
        "rfi",
        0.8,
        alts=[
            {"type": "submittal", "confidence": 0.2},
            {"type": "totally_made_up", "confidence": 0.7},  # not in taxonomy -> dropped
            {"type": "letter", "confidence": 0.1},
        ],
        rationale="Has RFI in title and routing language.",
    )
    client = FakeAsyncClient([(200, body)])
    classifier = AnthropicClassifier(api_key="sk-test", client=client)

    result = await classifier.classify(_parsed(), taxonomy)

    assert result.predicted_type == "rfi"
    assert {a.type for a in result.alternatives} == {"submittal", "letter"}
    # Alternatives sorted descending by confidence.
    assert [a.confidence for a in result.alternatives] == sorted(
        [a.confidence for a in result.alternatives], reverse=True
    )
    assert result.rationale.startswith("Has RFI")


@pytest.mark.asyncio
async def test_clamps_out_of_range_confidence() -> None:
    taxonomy = Taxonomy.starter()
    # LLM returns confidence > 1 — must be clamped.
    body = _anthropic_ok("rfi", 1.5)
    client = FakeAsyncClient([(200, body)])
    classifier = AnthropicClassifier(api_key="sk-test", client=client)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_unknown_type_falls_back_to_unclassified() -> None:
    taxonomy = Taxonomy.starter()
    body = _anthropic_ok("not_in_taxonomy", 0.5)
    client = FakeAsyncClient([(200, body)])
    classifier = AnthropicClassifier(api_key="sk-test", client=client)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.predicted_type == taxonomy.unclassified_type


@pytest.mark.asyncio
async def test_http_error_degrades_to_novel_pattern() -> None:
    taxonomy = Taxonomy.starter()
    # Three 500s — retries exhaust, then degrade.
    client = FakeAsyncClient(
        [
            (500, {"error": "boom"}),
            (500, {"error": "boom"}),
            (500, {"error": "boom"}),
        ]
    )
    classifier = AnthropicClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.confidence == 0.0
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    assert "llm_error" in result.signals
    assert result.signals["llm_error"] == 1.0
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_network_exception_degrades_to_novel_pattern() -> None:
    taxonomy = Taxonomy.starter()
    # Three network failures — retries exhaust, then degrade.
    client = FakeAsyncClient(
        [
            httpx.ConnectError("nope", request=None),  # type: ignore[arg-type]
            httpx.ConnectError("nope", request=None),  # type: ignore[arg-type]
            httpx.ConnectError("nope", request=None),  # type: ignore[arg-type]
        ]
    )
    classifier = AnthropicClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.confidence == 0.0
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient(
        [
            (429, {"error": "rate"}),
            (429, {"error": "rate"}),
            (200, _anthropic_ok("rfi", 0.9)),
        ]
    )
    classifier = AnthropicClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.predicted_type == "rfi"
    assert result.confidence == 0.9
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_retries_on_500_then_succeeds() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient(
        [
            (500, {"error": "boom"}),
            (502, {"error": "upstream"}),
            (200, _anthropic_ok("rfi", 0.9)),
        ]
    )
    classifier = AnthropicClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.predicted_type == "rfi"
    assert result.confidence == 0.9
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_retries_on_network_error_then_succeeds() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient(
        [
            httpx.ConnectError("x", request=None),  # type: ignore[arg-type]
            (200, _anthropic_ok("rfi", 0.85)),
        ]
    )
    classifier = AnthropicClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.predicted_type == "rfi"
    assert result.confidence == 0.85
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_non_retryable_4xx_does_not_retry() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient([(401, {"error": "auth"})])
    classifier = AnthropicClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert len(client.calls) == 1
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_sleep_uses_exponential_backoff() -> None:
    taxonomy = Taxonomy.starter()
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    client = FakeAsyncClient(
        [
            (500, {"error": "boom"}),
            (500, {"error": "boom"}),
            (500, {"error": "boom"}),
        ]
    )
    classifier = AnthropicClassifier(api_key="sk-test", client=client, sleep=fake_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    # Two sleeps for three attempts: 1.0 * 2^0, 1.0 * 2^1.
    assert sleeps == [1.0, 2.0]


@pytest.mark.asyncio
async def test_malformed_json_degrades_to_novel_pattern() -> None:
    taxonomy = Taxonomy.starter()
    body = {
        "content": [{"type": "text", "text": "this is not json at all"}],
    }
    client = FakeAsyncClient([(200, body)])
    classifier = AnthropicClassifier(api_key="sk-test", client=client)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.confidence == 0.0
    assert result.uncertainty_reason == "NOVEL_PATTERN"


@pytest.mark.asyncio
async def test_extracts_json_when_surrounded_by_prose() -> None:
    taxonomy = Taxonomy.starter()
    body = {
        "content": [
            {
                "type": "text",
                "text": (
                    "Sure — here is my classification: "
                    + json.dumps({"predicted_type": "rfi", "confidence": 0.7, "alternatives": []})
                    + " hope that helps."
                ),
            }
        ]
    }
    client = FakeAsyncClient([(200, body)])
    classifier = AnthropicClassifier(api_key="sk-test", client=client)
    result = await classifier.classify(_parsed(), taxonomy)
    assert result.predicted_type == "rfi"


@pytest.mark.asyncio
async def test_missing_api_key_raises_only_when_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Construction must not raise.
    classifier = AnthropicClassifier(client=FakeAsyncClient([]))
    taxonomy = Taxonomy.starter()
    result = await classifier.classify(_parsed(), taxonomy)
    # The wrapper catches the RuntimeError and degrades to NOVEL_PATTERN.
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    assert "ANTHROPIC_API_KEY" in result.rationale or "unhandled" in result.rationale


def test_provider_name() -> None:
    assert AnthropicClassifier(api_key="x").provider_name == "anthropic"

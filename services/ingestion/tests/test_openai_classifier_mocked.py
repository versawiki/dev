"""OpenAIClassifier tests — fully mocked, no network.

Mirrors the retry-coverage tests in `test_anthropic_classifier_mocked.py`
for the secondary fallback provider. Uses an injected fake
`httpx.AsyncClient` and a no-op sleep so the suite stays fast.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from versawiki_ingestion.classification import OpenAIClassifier
from versawiki_ingestion.classification.llm_provider import OPENAI_CHAT_URL
from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.parsers.base import ParseResult


# ----------------------------------------------------------------------
# Fake httpx client
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


def _openai_ok(predicted_type: str, confidence: float) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "predicted_type": predicted_type,
                            "confidence": confidence,
                            "alternatives": [],
                        }
                    )
                }
            }
        ]
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
async def test_retries_on_429_then_succeeds() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient(
        [
            (429, {"error": "rate"}),
            (429, {"error": "rate"}),
            (200, _openai_ok("rfi", 0.9)),
        ]
    )
    classifier = OpenAIClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.predicted_type == "rfi"
    assert result.confidence == 0.9
    assert len(client.calls) == 3
    # Verify the URL while we're here.
    assert client.calls[0]["url"] == OPENAI_CHAT_URL


@pytest.mark.asyncio
async def test_retries_on_500_then_succeeds() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient(
        [
            (500, {"error": "boom"}),
            (502, {"error": "upstream"}),
            (200, _openai_ok("rfi", 0.88)),
        ]
    )
    classifier = OpenAIClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.predicted_type == "rfi"
    assert result.confidence == 0.88
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_http_error_degrades_after_exhaustion() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient(
        [
            (500, {"error": "boom"}),
            (500, {"error": "boom"}),
            (500, {"error": "boom"}),
        ]
    )
    classifier = OpenAIClassifier(api_key="sk-test", client=client, sleep=_noop_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.confidence == 0.0
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    assert "llm_error" in result.signals
    assert result.signals["llm_error"] == 1.0
    assert len(client.calls) == 3


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
    classifier = OpenAIClassifier(api_key="sk-test", client=client, sleep=fake_sleep)

    result = await classifier.classify(_parsed(), taxonomy)
    assert result.uncertainty_reason == "NOVEL_PATTERN"
    # Two sleeps for three attempts: 1.0 * 2^0, 1.0 * 2^1.
    assert sleeps == [1.0, 2.0]


def test_provider_name() -> None:
    assert OpenAIClassifier(api_key="x").provider_name == "openai"

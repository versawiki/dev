"""Tests for `OpenAIEmbeddingProvider` — fully mocked, no network.

We don't have `respx`, so we inject a fake `httpx.AsyncClient` via the
provider's `client=` constructor argument. The fake records each `.post()`
call (URL, json, headers) and returns canned `httpx.Response` objects keyed
to a scripted sequence.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from versawiki_ingestion.embedding import EMBEDDING_DIM, OpenAIEmbeddingProvider


# ----------------------------------------------------------------------
# Fake AsyncClient — replays a scripted sequence of responses.
# ----------------------------------------------------------------------


class FakeAsyncClient:
    """Minimal stand-in for httpx.AsyncClient — only what the provider calls."""

    def __init__(self, responses: list[Any]) -> None:
        # `responses` is a list of either `httpx.Response`, `Exception`, or a
        # `(status_code, body_dict)` tuple. Consumed in order.
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
        # (status_code, body_dict)
        status, body = item
        return _make_response(status, body)

    async def aclose(self) -> None:
        return None


def _make_response(status: int, body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(status_code=status, content=json.dumps(body).encode("utf-8"))


def _ok_body(n: int) -> dict[str, Any]:
    """Build a valid OpenAI embeddings response with `n` vectors."""
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": [0.0] * EMBEDDING_DIM}
            for i in range(n)
        ],
        "model": "text-embedding-3-large",
        "usage": {"prompt_tokens": n, "total_tokens": n},
    }


async def _noop_sleep(_s: float) -> None:
    return None


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sends_dimensions_1024_in_payload() -> None:
    client = FakeAsyncClient([(200, _ok_body(2))])
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    out = await provider.embed(["hello", "world"])
    assert len(out) == 2
    assert len(out[0]) == EMBEDDING_DIM
    # One HTTP call; payload has dimensions=1024 and the right model.
    assert len(client.calls) == 1
    body = client.calls[0]["json"]
    assert body["dimensions"] == 1024
    assert body["model"] == "text-embedding-3-large"
    assert body["input"] == ["hello", "world"]
    assert client.calls[0]["headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_batches_at_100() -> None:
    """201 texts should split into batches of 100, 100, 1 — three HTTP calls."""
    # Each call returns N vectors matching the input count.
    client = FakeAsyncClient(
        [
            (200, _ok_body(100)),
            (200, _ok_body(100)),
            (200, _ok_body(1)),
        ]
    )
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    texts = [f"text {i}" for i in range(201)]
    out = await provider.embed(texts)
    assert len(out) == 201
    assert len(client.calls) == 3
    assert len(client.calls[0]["json"]["input"]) == 100
    assert len(client.calls[1]["json"]["input"]) == 100
    assert len(client.calls[2]["json"]["input"]) == 1


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds() -> None:
    client = FakeAsyncClient(
        [
            (429, {"error": {"message": "rate limited"}}),
            (200, _ok_body(1)),
        ]
    )
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    out = await provider.embed(["once"])
    assert len(out) == 1
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_retries_on_5xx_then_succeeds() -> None:
    client = FakeAsyncClient(
        [
            (502, {"error": "upstream"}),
            (500, {"error": "internal"}),
            (200, _ok_body(1)),
        ]
    )
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    out = await provider.embed(["once"])
    assert len(out) == 1
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_raises_after_max_attempts_on_repeated_429() -> None:
    client = FakeAsyncClient(
        [
            (429, {"error": "rl"}),
            (429, {"error": "rl"}),
            (429, {"error": "rl"}),
        ]
    )
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test", client=client, sleep=_noop_sleep, max_attempts=3
    )
    with pytest.raises(RuntimeError) as exc:
        await provider.embed(["once"])
    assert "429" in str(exc.value)
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_non_retryable_4xx_raises_immediately() -> None:
    client = FakeAsyncClient([(400, {"error": "bad request"})])
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    with pytest.raises(RuntimeError) as exc:
        await provider.embed(["once"])
    assert "400" in str(exc.value)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_missing_api_key_raises_at_first_call_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Construction must not raise.
    provider = OpenAIEmbeddingProvider()
    # First call without a key must raise.
    with pytest.raises(RuntimeError) as exc:
        await provider.embed(["x"])
    assert "OPENAI_API_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    client = FakeAsyncClient([(200, _ok_body(1))])
    provider = OpenAIEmbeddingProvider(client=client, sleep=_noop_sleep)
    await provider.embed(["x"])
    assert client.calls[0]["headers"]["Authorization"] == "Bearer sk-from-env"


@pytest.mark.asyncio
async def test_response_with_wrong_dimension_raises() -> None:
    bad = {
        "data": [
            {"index": 0, "embedding": [0.0] * 512},  # wrong dim
        ]
    }
    client = FakeAsyncClient([(200, bad)])
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    with pytest.raises(ValueError) as exc:
        await provider.embed(["x"])
    assert "dim" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_response_with_wrong_count_raises() -> None:
    bad = {"data": [{"index": 0, "embedding": [0.0] * EMBEDDING_DIM}]}
    client = FakeAsyncClient([(200, bad)])
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    with pytest.raises(ValueError):
        await provider.embed(["a", "b"])


@pytest.mark.asyncio
async def test_empty_input_skips_http() -> None:
    client = FakeAsyncClient([])  # would error if any request was made
    provider = OpenAIEmbeddingProvider(api_key="sk-test", client=client, sleep=_noop_sleep)
    assert await provider.embed([]) == []
    assert client.calls == []


def test_provider_name() -> None:
    assert OpenAIEmbeddingProvider(api_key="x").provider_name == "openai"
    assert OpenAIEmbeddingProvider(api_key="x").dimension == EMBEDDING_DIM

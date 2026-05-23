"""Tests for the `(catch-all)` annotation in the classifier user prompt.

The system prompt promises the LLM: "pick the taxonomy's catch-all type
(it will be labelled as such)". This test module pins that contract:

  1. `render_user_prompt` annotates only the names passed via
     `catch_all_types`, with the literal "(catch-all)" suffix.
  2. The legacy call shape (no `catch_all_types` argument) is unchanged.
  3. The Anthropic and OpenAI classifiers actually wire the taxonomy's
     `default_type` / `unclassified_type` into that argument, so the LLM
     receives the annotation in the user message.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from versawiki_ingestion.classification import (
    AnthropicClassifier,
    OpenAIClassifier,
)
from versawiki_ingestion.classification.prompts import render_user_prompt
from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.parsers.base import ParseResult


# ----------------------------------------------------------------------
# Fake httpx client — same pattern as test_anthropic_classifier_mocked.py
# ----------------------------------------------------------------------


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
        status, body = item
        return httpx.Response(
            status_code=status, content=json_dumps(body).encode("utf-8")
        )

    async def aclose(self) -> None:
        return None


def json_dumps(d: dict[str, Any]) -> str:
    return json.dumps(d)


def _anthropic_ok(predicted_type: str, confidence: float) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "predicted_type": predicted_type,
                        "confidence": confidence,
                        "alternatives": [],
                        "rationale": "",
                    }
                ),
            }
        ]
    }


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
# Direct render_user_prompt tests
# ----------------------------------------------------------------------


def test_render_user_prompt_annotates_catch_all_only() -> None:
    entries = [
        ("rfi", "Request for Information"),
        ("submittal", "Submittal package"),
        ("general_document", "Catch-all bucket"),
    ]
    out = render_user_prompt(
        _parsed(),
        entries,
        source_uri="x.txt",
        catch_all_types={"general_document"},
    )
    # The catch-all type gets the suffix.
    assert "- general_document (catch-all): Catch-all bucket" in out
    # Non-catch-all types keep the legacy form (no "(catch-all)" suffix on
    # their line).
    assert "- rfi: Request for Information" in out
    assert "- submittal: Submittal package" in out
    # Make sure no spurious annotation leaked onto non-catch-all lines.
    assert "rfi (catch-all)" not in out
    assert "submittal (catch-all)" not in out


def test_render_user_prompt_no_annotation_when_default_empty() -> None:
    entries = [
        ("rfi", "Request for Information"),
        ("general_document", "Catch-all bucket"),
    ]
    # Default: no catch_all_types passed at all.
    out_default = render_user_prompt(_parsed(), entries, source_uri="x.txt")
    assert "(catch-all)" not in out_default
    assert "- general_document: Catch-all bucket" in out_default

    # Explicit empty iterable — same behaviour.
    out_empty = render_user_prompt(
        _parsed(), entries, source_uri="x.txt", catch_all_types=()
    )
    assert "(catch-all)" not in out_empty


def test_render_user_prompt_multiple_catch_alls() -> None:
    entries = [
        ("rfi", "Request for Information"),
        ("general_document", "Catch-all bucket"),
        ("unclassified", "Fallback fallback"),
    ]
    out = render_user_prompt(
        _parsed(),
        entries,
        catch_all_types={"general_document", "unclassified"},
    )
    assert "- general_document (catch-all): Catch-all bucket" in out
    assert "- unclassified (catch-all): Fallback fallback" in out
    assert "- rfi: Request for Information" in out


# ----------------------------------------------------------------------
# Integration: classifiers pass the catch-all set into the user prompt
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_classifier_sends_catch_all_annotation() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient([(200, _anthropic_ok("rfi", 0.9))])
    classifier = AnthropicClassifier(api_key="sk-test", client=client)

    await classifier.classify(_parsed(), taxonomy, source_uri="rfi_042.txt")

    assert len(client.calls) == 1
    user_text = client.calls[0]["json"]["messages"][0]["content"]
    # The starter taxonomy's default_type (catch-all) appears with the
    # annotation in the rendered user message.
    default_name = taxonomy.default_type
    assert f"- {default_name} (catch-all):" in user_text
    # The unclassified type, if distinct, is also annotated.
    if taxonomy.unclassified_type != taxonomy.default_type:
        assert f"- {taxonomy.unclassified_type} (catch-all):" in user_text
    # A non-catch-all seed type ("rfi" is in the starter taxonomy) should
    # NOT carry the annotation.
    assert "- rfi (catch-all):" not in user_text
    assert "- rfi:" in user_text


@pytest.mark.asyncio
async def test_openai_classifier_sends_catch_all_annotation() -> None:
    taxonomy = Taxonomy.starter()
    client = FakeAsyncClient([(200, _openai_ok("rfi", 0.9))])
    classifier = OpenAIClassifier(api_key="sk-test", client=client)

    await classifier.classify(_parsed(), taxonomy, source_uri="rfi_042.txt")

    assert len(client.calls) == 1
    # OpenAI puts the user prompt as messages[1] (messages[0] is the system).
    messages = client.calls[0]["json"]["messages"]
    user_msg = next(m for m in messages if m["role"] == "user")
    user_text = user_msg["content"]
    default_name = taxonomy.default_type
    assert f"- {default_name} (catch-all):" in user_text
    if taxonomy.unclassified_type != taxonomy.default_type:
        assert f"- {taxonomy.unclassified_type} (catch-all):" in user_text
    assert "- rfi (catch-all):" not in user_text
    assert "- rfi:" in user_text

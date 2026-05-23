"""LLM-driven taxonomy labelling for cluster results.

Given a `ClusterResult` and the underlying ChunkRecords, an
``LLMTaxonomyProposer`` returns one ``ProposedLabel`` per cluster.

Three providers ship:

  * `StubTaxonomyProposer` — deterministic, network-free. Pulls the most
    frequent non-stopword tokens from each cluster's chunks and assembles
    a label like ``"cluster_<top1>_<top2>"``. Used in tests; same clusters
    -> same labels.
  * `AnthropicTaxonomyProposer` — primary in production. Calls
    `claude-sonnet-4-5` via `/v1/messages` with a single prompt per
    cluster.
  * `OpenAITaxonomyProposer` — secondary fallback. Same shape, OpenAI
    chat-completions.

Both HTTP providers fall back to the stub's logic on any error (network,
malformed JSON, etc.) so a flaky LLM never breaks induction — the cluster
still gets a label, just a less polished one.

Tests never hit the network; the HTTP providers accept an injected
`httpx.AsyncClient`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

import httpx

from ..pipeline.models import ChunkRecord
from .clusterer import ClusterResult


# ----------------------------------------------------------------------
# Data shapes
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedLabel:
    """One LLM-proposed label for a cluster.

    ``cluster_id`` matches the integer id from ``ClusterResult.assignments``.
    ``label`` is a short tenant-private string. ``confidence`` is the LLM's
    own [0,1] self-rating (or 0.5 for the stub, which has no LLM signal).
    """

    cluster_id: int
    label: str
    confidence: float = 0.5


# ----------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------


@runtime_checkable
class LLMTaxonomyProposer(Protocol):
    """Propose human-readable labels for a `ClusterResult`."""

    name: str

    async def propose(
        self,
        cluster_result: ClusterResult,
        chunks: Sequence[ChunkRecord],
    ) -> list[ProposedLabel]: ...


# ----------------------------------------------------------------------
# Stub — deterministic, no network.
# ----------------------------------------------------------------------


_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "this", "that", "these",
        "those", "have", "has", "are", "was", "were", "been", "being",
        "any", "all", "but", "not", "you", "your", "our", "their", "its",
        "they", "them", "his", "her", "him", "she", "she's", "he's",
        "will", "would", "could", "should", "may", "might", "must",
        "into", "onto", "of", "to", "in", "on", "at", "by", "as", "is",
        "be", "or", "an", "a", "it", "if", "so", "we", "us", "do",
        "did", "does", "doing", "done", "i", "me", "my", "mine",
    }
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _propose_label_stub(
    cluster_id: int,
    cluster_chunks: Sequence[ChunkRecord],
) -> ProposedLabel:
    """Deterministic label from top tokens in the cluster's chunks."""
    counts: Counter[str] = Counter()
    for chunk in cluster_chunks:
        for tok in _WORD_RE.findall(chunk.text.lower()):
            if len(tok) <= 2 or tok in _STOPWORDS or tok.isdigit():
                continue
            counts[tok] += 1
    if not counts:
        return ProposedLabel(
            cluster_id=cluster_id, label=f"cluster_{cluster_id}", confidence=0.5
        )
    # Take the top 2 tokens (alphabetical tiebreak for determinism).
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [tok for tok, _ in ranked[:2]]
    label = "cluster_" + "_".join(top)
    return ProposedLabel(cluster_id=cluster_id, label=label, confidence=0.5)


class StubTaxonomyProposer:
    """Deterministic proposer used in tests and as the HTTP-provider fallback.

    Given the same cluster assignments and chunk texts, it returns the
    same labels every time — no salt, no randomness, no network.
    """

    name = "stub"

    async def propose(
        self,
        cluster_result: ClusterResult,
        chunks: Sequence[ChunkRecord],
    ) -> list[ProposedLabel]:
        by_cluster: dict[int, list[ChunkRecord]] = {}
        # Index chunks by hash so we can look them up per-assignment.
        by_hash = {c.chunk_content_hash: c for c in chunks}
        for assn in cluster_result.assignments:
            chunk = by_hash.get(assn.chunk_content_hash)
            if chunk is None:
                continue
            by_cluster.setdefault(assn.cluster_id, []).append(chunk)

        # One label per cluster id that actually has chunks. We deliberately
        # iterate over cluster_centroids range so empty clusters still get
        # a placeholder label — keeps cluster_id -> label a total mapping.
        out: list[ProposedLabel] = []
        for ci in range(cluster_result.num_clusters):
            members = by_cluster.get(ci, [])
            out.append(_propose_label_stub(ci, members))
        return out


# ----------------------------------------------------------------------
# Anthropic — primary
# ----------------------------------------------------------------------


ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-5"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 200
DEFAULT_TIMEOUT_S = 30.0

_LABEL_SYSTEM_PROMPT = (
    "You are an ontology labeller. Given representative excerpts from a "
    "single cluster of documents, return ONE short snake_case label (1-4 "
    "words) that names the topic, plus a self-rated confidence in [0,1]. "
    "Reply with a JSON object of the shape "
    '{"label": "...", "confidence": 0.0}. No prose.'
)


def _render_user_prompt(chunks: Sequence[ChunkRecord], *, max_excerpt: int = 600) -> str:
    excerpts = []
    for i, c in enumerate(chunks[:5]):
        text = c.text.strip().replace("\n\n\n", "\n\n")
        if len(text) > max_excerpt:
            text = text[:max_excerpt] + "..."
        excerpts.append(f"[doc {i + 1}] {text}")
    return (
        "Cluster excerpts:\n\n"
        + "\n\n".join(excerpts)
        + "\n\nReturn the JSON object now."
    )


class _HTTPProposerMixin:
    """Shared parsing logic for HTTP-based proposers."""

    @staticmethod
    def _parse_label_json(text: str, *, cluster_id: int) -> Optional[ProposedLabel]:
        if not text:
            return None
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        label = str(data.get("label", "")).strip()
        if not label:
            return None
        try:
            conf = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        return ProposedLabel(cluster_id=cluster_id, label=label, confidence=conf)


class AnthropicTaxonomyProposer(_HTTPProposerMixin):
    """Anthropic-backed cluster labeller. One HTTP call per cluster."""

    name = "anthropic"

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
        self._sleep = sleep

    async def propose(
        self,
        cluster_result: ClusterResult,
        chunks: Sequence[ChunkRecord],
    ) -> list[ProposedLabel]:
        if not cluster_result.cluster_centroids:
            return []
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            by_hash = {c.chunk_content_hash: c for c in chunks}
            by_cluster: dict[int, list[ChunkRecord]] = {}
            for assn in cluster_result.assignments:
                ch = by_hash.get(assn.chunk_content_hash)
                if ch is not None:
                    by_cluster.setdefault(assn.cluster_id, []).append(ch)

            out: list[ProposedLabel] = []
            for ci in range(cluster_result.num_clusters):
                members = by_cluster.get(ci, [])
                if not members:
                    out.append(_propose_label_stub(ci, []))
                    continue
                label = await self._call_one(client, ci, members)
                out.append(label or _propose_label_stub(ci, members))
            return out
        finally:
            if self._owns_client:
                await client.aclose()

    async def _call_one(
        self,
        client: httpx.AsyncClient,
        cluster_id: int,
        members: Sequence[ChunkRecord],
    ) -> Optional[ProposedLabel]:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": _LABEL_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": _render_user_prompt(members)}],
        }
        headers = {
            "x-api-key": self._resolve_api_key(),
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }
        try:
            resp = await client.post(
                ANTHROPIC_MESSAGES_URL, json=payload, headers=headers
            )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            body = resp.json()
        except (ValueError, json.JSONDecodeError):
            return None
        content = body.get("content", []) or []
        text_parts = [
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return self._parse_label_json("\n".join(text_parts), cluster_id=cluster_id)

    def _resolve_api_key(self) -> str:
        key = self._api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "AnthropicTaxonomyProposer: ANTHROPIC_API_KEY is not set."
            )
        return key


# ----------------------------------------------------------------------
# OpenAI — secondary
# ----------------------------------------------------------------------


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


class OpenAITaxonomyProposer(_HTTPProposerMixin):
    """OpenAI-backed cluster labeller. Same shape as the Anthropic provider."""

    name = "openai"

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

    async def propose(
        self,
        cluster_result: ClusterResult,
        chunks: Sequence[ChunkRecord],
    ) -> list[ProposedLabel]:
        if not cluster_result.cluster_centroids:
            return []
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            by_hash = {c.chunk_content_hash: c for c in chunks}
            by_cluster: dict[int, list[ChunkRecord]] = {}
            for assn in cluster_result.assignments:
                ch = by_hash.get(assn.chunk_content_hash)
                if ch is not None:
                    by_cluster.setdefault(assn.cluster_id, []).append(ch)

            out: list[ProposedLabel] = []
            for ci in range(cluster_result.num_clusters):
                members = by_cluster.get(ci, [])
                if not members:
                    out.append(_propose_label_stub(ci, []))
                    continue
                label = await self._call_one(client, ci, members)
                out.append(label or _propose_label_stub(ci, members))
            return out
        finally:
            if self._owns_client:
                await client.aclose()

    async def _call_one(
        self,
        client: httpx.AsyncClient,
        cluster_id: int,
        members: Sequence[ChunkRecord],
    ) -> Optional[ProposedLabel]:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _LABEL_SYSTEM_PROMPT},
                {"role": "user", "content": _render_user_prompt(members)},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._resolve_api_key()}",
            "Content-Type": "application/json",
        }
        try:
            resp = await client.post(OPENAI_CHAT_URL, json=payload, headers=headers)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            body = resp.json()
        except (ValueError, json.JSONDecodeError):
            return None
        choices = body.get("choices", []) or []
        if not choices:
            return None
        first = choices[0] or {}
        msg = first.get("message", {}) or {}
        return self._parse_label_json(
            str(msg.get("content", "")), cluster_id=cluster_id
        )

    def _resolve_api_key(self) -> str:
        key = self._api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAITaxonomyProposer: OPENAI_API_KEY is not set."
            )
        return key

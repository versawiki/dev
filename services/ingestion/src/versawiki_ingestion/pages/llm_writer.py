"""`LLMPageWriter` Protocol + three impls (Anthropic, OpenAI, Stub).

The page builder needs to turn N chunks + an ontology node label into
human-readable prose. That's an LLM call in production; in tests it's
the ``StubPageWriter`` — deterministic, network-free, but it *reads*
the chunks (so a test can assert the writer was given the right
inputs).

The Protocol intentionally exposes two methods:

  - ``propose_title(node_label, top_chunks) -> str``
  - ``write_summary(node_label, top_chunks) -> str``

Future skills may add ``write_section`` etc.; we keep the surface
small for now so the contract is easy to stub.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from ..pipeline.models import ChunkRecord


@runtime_checkable
class LLMPageWriter(Protocol):
    """Async writer the page builder calls.

    Implementations should be deterministic given the same inputs
    where possible — the stub is fully deterministic. Real providers
    inherit their model's stability story.
    """

    provider_name: str

    async def propose_title(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        """Return a short, human-readable page title."""
        ...

    async def write_summary(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        """Return a 200-500 word summary paragraph."""
        ...


# ---------------------------------------------------------------------------
# StubPageWriter — deterministic, network-free, used in every test.
# ---------------------------------------------------------------------------


class StubPageWriter:
    """Deterministic templated writer.

    Reads the chunks (so a test can verify the writer was passed the
    correct inputs) but never calls the network. Output is stable
    across runs for identical inputs — that's how the idempotence
    tests assert content hashes don't drift.
    """

    provider_name = "stub"

    def __init__(self) -> None:
        # Track which inputs were seen — tests can assert against this
        # if they want to confirm the writer was actually called.
        self.title_calls: list[tuple[str, tuple[str, ...]]] = []
        self.summary_calls: list[tuple[str, tuple[str, ...]]] = []

    async def propose_title(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        chunk_hashes = tuple(c.chunk_content_hash for c in top_chunks)
        self.title_calls.append((node_label, chunk_hashes))
        # Title strategy: capitalise the node label and tack on the
        # source count for disambiguation when two nodes share a label.
        n = len(top_chunks)
        # Replace underscores / dashes with spaces; title-case words.
        clean = node_label.replace("_", " ").replace("-", " ").strip()
        if not clean:
            clean = "untitled"
        words = [w.capitalize() if w.islower() else w for w in clean.split()]
        return " ".join(words) if n == 0 else " ".join(words)

    async def write_summary(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        chunk_hashes = tuple(c.chunk_content_hash for c in top_chunks)
        self.summary_calls.append((node_label, chunk_hashes))
        # Templated summary — deterministic and traceable. Production
        # writers compose this with a real prompt; the stub keeps the
        # structure so downstream tests can pattern-match.
        bits: list[str] = []
        bits.append(
            f"This page summarises the topic '{node_label}'."
        )
        bits.append(
            f"It was built from {len(top_chunks)} source chunks across "
            f"{len({c.source_uri for c in top_chunks})} distinct documents."
        )
        if top_chunks:
            # Quote a small slice of the first chunk so the summary is
            # at least visibly grounded in the inputs.
            head = top_chunks[0].text.strip().splitlines()[0]
            head = head[:200]
            bits.append(f"Representative excerpt: {head!r}.")
        # Pad out to roughly 200 words using a deterministic filler
        # derived from the inputs so the page is realistically sized
        # without being a fixed lorem-ipsum.
        digest = hashlib.sha256(
            "|".join(chunk_hashes).encode("utf-8")
        ).hexdigest()
        bits.append(
            "The chunks under this node share a common theme as identified "
            "by the ontology inducer; readers can drill into individual "
            "citations via the search tool. This summary is generated "
            "deterministically by the test stub writer and reflects the "
            "shape of the production LLM output without calling the "
            f"network. Content fingerprint: {digest[:16]}."
        )
        return " ".join(bits)


# ---------------------------------------------------------------------------
# AnthropicPageWriter — real provider, lazy httpx, falls back to stub on error.
# ---------------------------------------------------------------------------


class AnthropicPageWriter:
    """Claude-backed writer.

    Implementation parity with the other Anthropic-backed components
    in this service (taxonomy proposer, classifier): a thin httpx call
    with a clear prompt, falling back to ``StubPageWriter`` if the
    model fails or no API key is configured. The production caller
    constructs this with an API key.
    """

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
        timeout_s: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._fallback = StubPageWriter()

    async def propose_title(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        if not self.api_key:
            return await self._fallback.propose_title(
                node_label=node_label, top_chunks=top_chunks
            )
        try:
            return await self._call(
                kind="title",
                node_label=node_label,
                top_chunks=top_chunks,
            )
        except Exception:  # noqa: BLE001 - fall back on any error
            return await self._fallback.propose_title(
                node_label=node_label, top_chunks=top_chunks
            )

    async def write_summary(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        if not self.api_key:
            return await self._fallback.write_summary(
                node_label=node_label, top_chunks=top_chunks
            )
        try:
            return await self._call(
                kind="summary",
                node_label=node_label,
                top_chunks=top_chunks,
            )
        except Exception:  # noqa: BLE001
            return await self._fallback.write_summary(
                node_label=node_label, top_chunks=top_chunks
            )

    async def _call(
        self,
        *,
        kind: str,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        # Lazy import so the package imports cleanly without httpx.
        import httpx  # noqa: WPS433 - intentional lazy import

        prompt = _compose_prompt(kind, node_label, top_chunks)
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
            r.raise_for_status()
            body = r.json()
            for block in body.get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    return block["text"].strip()
            raise RuntimeError("Anthropic response had no text block")


# ---------------------------------------------------------------------------
# OpenAIPageWriter — secondary provider, same fallback story.
# ---------------------------------------------------------------------------


class OpenAIPageWriter:
    """OpenAI-backed writer; falls back to the stub on any failure."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        timeout_s: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._fallback = StubPageWriter()

    async def propose_title(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        if not self.api_key:
            return await self._fallback.propose_title(
                node_label=node_label, top_chunks=top_chunks
            )
        try:
            return await self._call("title", node_label, top_chunks)
        except Exception:  # noqa: BLE001
            return await self._fallback.propose_title(
                node_label=node_label, top_chunks=top_chunks
            )

    async def write_summary(
        self,
        *,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        if not self.api_key:
            return await self._fallback.write_summary(
                node_label=node_label, top_chunks=top_chunks
            )
        try:
            return await self._call("summary", node_label, top_chunks)
        except Exception:  # noqa: BLE001
            return await self._fallback.write_summary(
                node_label=node_label, top_chunks=top_chunks
            )

    async def _call(
        self,
        kind: str,
        node_label: str,
        top_chunks: list[ChunkRecord],
    ) -> str:
        import httpx

        prompt = _compose_prompt(kind, node_label, top_chunks)
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            r.raise_for_status()
            body = r.json()
            choices = body.get("choices") or []
            if choices and choices[0].get("message", {}).get("content"):
                return choices[0]["message"]["content"].strip()
            raise RuntimeError("OpenAI response had no content")


# ---------------------------------------------------------------------------
# Shared prompt composition (kept module-level so both providers share it).
# ---------------------------------------------------------------------------


def _compose_prompt(
    kind: str, node_label: str, top_chunks: list[ChunkRecord]
) -> str:
    excerpts = "\n\n".join(
        f"[chunk {i}] {c.text[:600]}" for i, c in enumerate(top_chunks[:10])
    )
    if kind == "title":
        return (
            f"You are writing a wiki page title for the topic '{node_label}'.\n"
            f"Source chunks:\n{excerpts}\n\n"
            "Return a short, capitalised title (5-10 words). No quotes."
        )
    return (
        f"You are writing a 200-500 word wiki summary for '{node_label}'.\n"
        f"Source chunks:\n{excerpts}\n\n"
        "Write a clear, factual summary grounded in the chunks. "
        "No bullet points; flowing prose."
    )


__all__ = [
    "AnthropicPageWriter",
    "LLMPageWriter",
    "OpenAIPageWriter",
    "StubPageWriter",
]

"""Embedding-provider factory.

Centralised so callers can pass a string (e.g. from a `Settings` object, a
tenant config row, or a CLI flag) and get back a configured provider. New
providers (`bge-m3`, `nomic`) plug in here without changing call-sites.
"""

from __future__ import annotations

from typing import Any

from .base import EmbeddingProvider
from .openai_provider import OpenAIEmbeddingProvider
from .stub_provider import StubEmbeddingProvider


def get_embedding_provider(name: str, settings: Any = None) -> EmbeddingProvider:
    """Resolve a provider name to a constructed `EmbeddingProvider`.

    Names:
    - `"openai"` — `text-embedding-3-large` truncated to 1024 dims.
    - `"stub"` — deterministic offline stub for tests.

    Future:
    - `"bge-m3"` — self-hosted BAAI/bge-m3 (M3+).
    - `"nomic"` — self-hosted nomic-embed-text-v2 (M3+).

    `settings` is intentionally typed as `Any` for now — the Backend ticket
    M1-BE-01 owns the settings shape and we don't want to circular-import it.
    Pass whatever your callsite has; providers ignore it today and consume
    selectively when they grow config knobs.
    """
    n = name.lower().strip()
    if n == "openai":
        # `settings` may carry `openai_api_key` / `openai_embedding_model`; if
        # not, the provider reads `OPENAI_API_KEY` at first call.
        api_key = _get_setting(settings, "openai_api_key", None)
        model = _get_setting(settings, "openai_embedding_model", None)
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        return OpenAIEmbeddingProvider(**kwargs)
    if n == "stub":
        return StubEmbeddingProvider()
    if n in ("bge-m3", "nomic"):
        raise NotImplementedError(
            f"Embedding provider '{name}' is reserved for M3+ "
            "(see DECISIONS.md 2026-05-22 embedding plumbing)."
        )
    raise ValueError(
        f"Unknown embedding provider '{name}'. Known: 'openai', 'stub'."
    )


def _get_setting(settings: Any, attr: str, default: Any) -> Any:
    """Tolerant getter: works for Pydantic settings, dicts, or plain objects."""
    if settings is None:
        return default
    if isinstance(settings, dict):
        return settings.get(attr, default)
    return getattr(settings, attr, default)

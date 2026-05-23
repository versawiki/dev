"""Tests for `StubEmbeddingProvider` — used pervasively in the rest of the suite.

The contract:

- dimension attribute == EMBEDDING_DIM (== 1024)
- embed() returns one vector per input, each of length EMBEDDING_DIM
- deterministic: same input -> same vector
- different inputs -> different vectors (extremely high probability)
- empty input list -> empty output list
"""

from __future__ import annotations

import pytest

from versawiki_ingestion.embedding import (
    EMBEDDING_DIM,
    EmbeddingProvider,
    StubEmbeddingProvider,
    get_embedding_provider,
)


def test_dimension_attribute_is_locked_at_1024() -> None:
    p = StubEmbeddingProvider()
    assert p.dimension == EMBEDDING_DIM == 1024


def test_provider_name() -> None:
    assert StubEmbeddingProvider().provider_name == "stub"


@pytest.mark.asyncio
async def test_embed_returns_one_vector_per_input() -> None:
    p = StubEmbeddingProvider()
    out = await p.embed(["hello", "world", "third"])
    assert len(out) == 3
    for v in out:
        assert len(v) == EMBEDDING_DIM
        assert all(isinstance(x, float) for x in v)


@pytest.mark.asyncio
async def test_embed_is_deterministic() -> None:
    p1 = StubEmbeddingProvider()
    p2 = StubEmbeddingProvider()
    a = await p1.embed(["same input"])
    b = await p2.embed(["same input"])
    assert a == b


@pytest.mark.asyncio
async def test_different_inputs_produce_different_vectors() -> None:
    p = StubEmbeddingProvider()
    a, b = await p.embed(["alpha", "beta"])
    # Vectors should not be identical for distinct inputs.
    assert a != b


@pytest.mark.asyncio
async def test_empty_input_returns_empty_output() -> None:
    p = StubEmbeddingProvider()
    assert await p.embed([]) == []


def test_protocol_compliance() -> None:
    p = StubEmbeddingProvider()
    # runtime_checkable Protocol — the stub must satisfy it structurally.
    assert isinstance(p, EmbeddingProvider)


def test_registry_resolves_stub() -> None:
    p = get_embedding_provider("stub")
    assert isinstance(p, StubEmbeddingProvider)
    assert p.dimension == EMBEDDING_DIM


def test_registry_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        get_embedding_provider("does-not-exist")


def test_registry_marks_future_providers_as_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        get_embedding_provider("bge-m3")
    with pytest.raises(NotImplementedError):
        get_embedding_provider("nomic")

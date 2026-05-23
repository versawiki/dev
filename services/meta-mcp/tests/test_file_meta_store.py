"""`FileMetaStore`: append, list/query, and concurrent-write safety."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from versawiki_meta_mcp.schema.observation import DomainObservationEnvelope
from versawiki_meta_mcp.store.file_store import FileMetaStore


SAFE_ANON_ID_A = "bc6be0b5-7901-48fb-ae49-69d47663a776"
SAFE_ANON_ID_B = "aaaaeeee-7901-48fb-ae49-aabbccddeeff"


def _make_envelope(
    *,
    tenant_anon_id: str = SAFE_ANON_ID_A,
    kind: str = "naming_convention",
    when: datetime | None = None,
) -> DomainObservationEnvelope:
    """Build a minimal-but-valid envelope for store tests."""

    when = when or datetime.now(timezone.utc)

    if kind == "naming_convention":
        payload = {
            "kind": "naming_convention",
            "applies_to": "drawing_number",
            "template": "<phase>-<discipline>",
            "token_vocabulary": ["phase", "discipline"],
            "sample_count_bucket": "51-200",
            "adherence_rate": 0.9,
        }
    elif kind == "ontology_shape":
        payload = {
            "kind": "ontology_shape",
            "depth": 3,
            "node_count_bucket": "11-50",
            "branching_factor_p50": 0.5,
            "branching_factor_p95": 0.8,
            "leaf_to_internal_ratio": 0.7,
            "kind_distribution": {"category": 5, "entity": 7},
            "induced_vs_seed_ratio": None,
        }
    else:
        raise ValueError(kind)

    return DomainObservationEnvelope.model_validate(
        {
            "event_id": str(uuid4()),
            "schema_version": "1.0.0",
            "observed_at_utc": when.isoformat(),
            "tenant_anon_id": tenant_anon_id,
            "opt_out_flag": False,
            "domain_signature_id": None,
            "payload": payload,
        }
    )


def _run(awaitable):
    return asyncio.run(awaitable)


def test_write_and_count(tmp_path: Path):
    store = FileMetaStore(tmp_path / "meta")
    env = _make_envelope()
    _run(store.write_observation(env))
    assert _run(store.count()) == 1
    assert store.path.exists()


def test_jsonl_line_per_record(tmp_path: Path):
    store = FileMetaStore(tmp_path / "meta")
    for _ in range(5):
        _run(store.write_observation(_make_envelope()))

    lines = [
        l for l in store.path.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(lines) == 5
    # Every line is valid JSON.
    for line in lines:
        record = json.loads(line)
        assert "payload" in record
        assert "tenant_anon_id" in record


def test_query_filters_by_tenant_anon_id(tmp_path: Path):
    store = FileMetaStore(tmp_path / "meta")
    _run(store.write_observation(_make_envelope(tenant_anon_id=SAFE_ANON_ID_A)))
    _run(store.write_observation(_make_envelope(tenant_anon_id=SAFE_ANON_ID_A)))
    _run(store.write_observation(_make_envelope(tenant_anon_id=SAFE_ANON_ID_B)))

    async def collect(tid):
        return [
            e async for e in store.query(tenant_anon_id=tid)
        ]

    assert len(_run(collect(SAFE_ANON_ID_A))) == 2
    assert len(_run(collect(SAFE_ANON_ID_B))) == 1


def test_query_filters_by_kind(tmp_path: Path):
    store = FileMetaStore(tmp_path / "meta")
    _run(store.write_observation(_make_envelope(kind="naming_convention")))
    _run(store.write_observation(_make_envelope(kind="ontology_shape")))

    async def by_kind(k):
        return [e async for e in store.query(kind=k)]

    assert len(_run(by_kind("naming_convention"))) == 1
    assert len(_run(by_kind("ontology_shape"))) == 1


def test_query_filters_by_time_window(tmp_path: Path):
    store = FileMetaStore(tmp_path / "meta")
    base = datetime.now(timezone.utc)
    old = base - timedelta(days=10)
    recent = base - timedelta(hours=1)

    _run(store.write_observation(_make_envelope(when=old)))
    _run(store.write_observation(_make_envelope(when=recent)))

    async def in_window(since):
        return [e async for e in store.query(since_utc=since)]

    assert len(_run(in_window(base - timedelta(days=30)))) == 2
    assert len(_run(in_window(base - timedelta(days=1)))) == 1


def test_query_respects_limit(tmp_path: Path):
    store = FileMetaStore(tmp_path / "meta")
    for _ in range(10):
        _run(store.write_observation(_make_envelope()))

    async def limited():
        return [e async for e in store.query(limit=3)]

    assert len(_run(limited())) == 3


def test_concurrent_writes_do_not_corrupt(tmp_path: Path):
    """Two async tasks calling `write_observation` concurrently must each
    produce a clean, complete JSONL line — never an interleaved record.
    """

    store = FileMetaStore(tmp_path / "meta")

    async def writer(n: int):
        for _ in range(n):
            await store.write_observation(_make_envelope())

    async def go():
        await asyncio.gather(writer(20), writer(20))

    _run(go())

    lines = [
        l for l in store.path.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(lines) == 40
    # Every line parses cleanly — proof of no interleaving.
    for line in lines:
        record = json.loads(line)
        assert "tenant_anon_id" in record
        # And every line round-trips through the schema.
        env = DomainObservationEnvelope.model_validate(record)
        assert env.tenant_anon_id == SAFE_ANON_ID_A


def test_query_on_empty_store(tmp_path: Path):
    store = FileMetaStore(tmp_path / "meta")

    async def collect():
        return [e async for e in store.query()]

    assert _run(collect()) == []

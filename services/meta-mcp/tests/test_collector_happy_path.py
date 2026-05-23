"""End-to-end: a principle-only raw event flows through the collector
and lands in the meta store. No audit-log entry is written.

This is the operational sibling of `test_pipeline_happy.py`: where that
test verifies the checker pipeline alone, this verifies the full
collector path (raw -> compute -> envelope -> checker -> store).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from versawiki_meta_mcp.audit.tenant_audit_log import TenantAuditLog
from versawiki_meta_mcp.collector.collector import (
    CollectorOutcome,
    SignatureCollector,
)
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig
from versawiki_meta_mcp.events.raw_event import RawOntologyShapeEvent
from versawiki_meta_mcp.events.subscriber import InProcessSubscriber
from versawiki_meta_mcp.store.file_store import FileMetaStore


SAFE_ANON_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


@pytest.fixture
def tenant_config() -> TenantSignatureConfig:
    return TenantSignatureConfig(
        tenant_anon_id=SAFE_ANON_ID,
        opt_out=False,
        type_vocab={"Drawing": "drawing"},
    )


@pytest.fixture
def meta_store(tmp_path: Path) -> FileMetaStore:
    return FileMetaStore(tmp_path / "meta")


@pytest.fixture
def audit_log(tmp_path: Path) -> TenantAuditLog:
    return TenantAuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def collector(tenant_config, meta_store, audit_log) -> SignatureCollector:
    return SignatureCollector(
        tenant_config=tenant_config,
        meta_store=meta_store,
        audit_log=audit_log,
    )


@pytest.fixture
def happy_raw_event() -> RawOntologyShapeEvent:
    return RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID,
        depth=4,
        node_count=80,
        # Ratio-style branching factors stay in [0,1] so the current numeric
        # checker accepts them (the spec-vs-impl mismatch on branching factor
        # is tracked in notes/mcp-builder.md).
        branching_factors=[0.0, 0.2, 0.3, 0.4, 0.5],
        kind_distribution={"category": 12, "entity": 30, "topic": 8},
    )


def _run(awaitable):
    return asyncio.run(awaitable)


def test_principle_only_event_lands_in_meta_store(
    collector, meta_store, audit_log, happy_raw_event
):
    result = _run(collector.process_one(happy_raw_event))

    assert result.outcome == CollectorOutcome.ACCEPTED
    assert result.envelope is not None
    assert result.envelope.payload.kind == "ontology_shape"
    # File should have exactly one line.
    assert _run(meta_store.count()) == 1
    # Audit log should not exist at all (no rejection happened).
    assert not audit_log.path.exists()


def test_subscriber_drains_through_run(
    collector, meta_store, audit_log, happy_raw_event
):
    sub = InProcessSubscriber()

    async def go():
        await sub.publish(happy_raw_event)
        await sub.publish(happy_raw_event)
        await sub.close()
        return await collector.run(sub)

    results = _run(go())
    assert len(results) == 2
    assert all(r.outcome == CollectorOutcome.ACCEPTED for r in results)
    assert _run(meta_store.count()) == 2
    assert not audit_log.path.exists()


def test_meta_store_query_filters_by_tenant_and_kind(
    collector, meta_store, happy_raw_event
):
    _run(collector.process_one(happy_raw_event))

    async def collect():
        out = []
        async for env in meta_store.query(
            tenant_anon_id=SAFE_ANON_ID, kind="ontology_shape"
        ):
            out.append(env)
        return out

    rows = _run(collect())
    assert len(rows) == 1
    assert rows[0].tenant_anon_id == SAFE_ANON_ID
    assert rows[0].payload.kind == "ontology_shape"

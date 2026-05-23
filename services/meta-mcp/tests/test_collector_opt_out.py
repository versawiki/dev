"""`tenant_config.opt_out=True` blocks every event at the opt-out gate.

The opt-out gate is the FIRST thing the collector checks. No signature
is computed, no envelope is built, no checker pipeline runs — the raw
event is hashed for the audit log and dropped.

This is a defensive choice. M1-MCP-05 owns the full opt-out behavior;
the collector simply honors the flag.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from versawiki_meta_mcp.audit.tenant_audit_log import TenantAuditLog
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage
from versawiki_meta_mcp.collector.collector import (
    CollectorOutcome,
    SignatureCollector,
)
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig
from versawiki_meta_mcp.events.raw_event import (
    RawNamingConventionEvent,
    RawOntologyShapeEvent,
)
from versawiki_meta_mcp.events.subscriber import InProcessSubscriber
from versawiki_meta_mcp.store.file_store import FileMetaStore


SAFE_ANON_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def opt_out_collector(tmp_path: Path):
    cfg = TenantSignatureConfig(tenant_anon_id=SAFE_ANON_ID, opt_out=True)
    meta_store = FileMetaStore(tmp_path / "meta")
    audit_log = TenantAuditLog(tmp_path / "audit.jsonl")
    collector = SignatureCollector(
        tenant_config=cfg,
        meta_store=meta_store,
        audit_log=audit_log,
    )
    return collector, meta_store, audit_log


def _read_audit(audit_log) -> list[dict]:
    if not audit_log.path.exists():
        return []
    return [
        json.loads(l)
        for l in audit_log.path.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]


def test_opt_out_drops_single_event(opt_out_collector):
    collector, meta_store, audit_log = opt_out_collector
    raw = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID,
        depth=2,
        node_count=20,
        branching_factors=[0.3, 0.4],
        kind_distribution={"category": 5},
    )
    result = _run(collector.process_one(raw))

    assert result.outcome == CollectorOutcome.OPT_OUT_DROPPED
    assert result.reason_code == ReasonCode.OPT_OUT
    assert result.stage == Stage.OPT_OUT_GATE
    assert _run(meta_store.count()) == 0

    audit = _read_audit(audit_log)
    assert len(audit) == 1
    assert audit[0]["reason_code"] == ReasonCode.OPT_OUT.value
    assert audit[0]["stage"] == Stage.OPT_OUT_GATE.value


def test_opt_out_drops_every_event_in_stream(opt_out_collector):
    collector, meta_store, audit_log = opt_out_collector
    sub = InProcessSubscriber()

    async def go():
        for i in range(7):
            raw = RawNamingConventionEvent(
                tenant_anon_id=SAFE_ANON_ID,
                applies_to="drawing_number",
                raw_template=f"<DD>-{i}",
                matched_count=i,
                sample_count=i + 1,
            )
            await sub.publish(raw)
        await sub.close()
        return await collector.run(sub)

    results = _run(go())
    assert len(results) == 7
    assert all(r.outcome == CollectorOutcome.OPT_OUT_DROPPED for r in results)
    assert _run(meta_store.count()) == 0
    assert len(_read_audit(audit_log)) == 7


def test_opt_out_audit_records_have_safe_shape(opt_out_collector):
    """Opt-out drops still respect the audit-log privacy invariant."""

    collector, _meta_store, audit_log = opt_out_collector
    raw = RawNamingConventionEvent(
        tenant_anon_id=SAFE_ANON_ID,
        applies_to="drawing_number",
        raw_template="<DD>",
        matched_count=1,
        sample_count=1,
        example_identifiers=["FORBIDDEN-EXAMPLE"],
    )
    _run(collector.process_one(raw))

    on_disk = audit_log.path.read_text(encoding="utf-8")
    assert "FORBIDDEN-EXAMPLE" not in on_disk
    # The record shape is exactly the four privacy-safe keys.
    entry = json.loads(on_disk.splitlines()[0])
    assert set(entry.keys()) == {"payload_hash", "reason_code", "stage", "timestamp"}

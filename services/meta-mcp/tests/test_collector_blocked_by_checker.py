"""A raw event whose envelope trips a checker is rejected.

Privacy-load-bearing test. If the assertion in this file ever flips to
"the envelope landed in the meta store anyway", that is a privacy
breach — the collector has stopped using the checker pipeline as a gate.

We trip the *forbidden-field-name* scanner by feeding a raw event whose
`tenant_type_counts` dict (mapped onto generic_type_counts) carries a
key the schema accepts but the forbidden-name scanner rejects when the
ingestion service has misconfigured the type_vocab.

We can also trip the PII regex by smuggling an email-shaped string
through the tenant_anon_id (which is the *only* free-string field on
the envelope after Pydantic strips everything else).
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
)
from versawiki_meta_mcp.store.file_store import FileMetaStore


# A tenant_anon_id that *looks* like a UUID but contains a phone-shape run.
# This trips the PII regex (per the over-eager-regex note in
# notes/mcp-builder.md) — a useful blunt instrument for *this* test, which
# just needs *something* downstream of the schema to fail.
PHONE_SHAPED_ANON_ID = "12345678-901-23-4567-69d47663a776"
SAFE_ANON_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def meta_store(tmp_path: Path) -> FileMetaStore:
    return FileMetaStore(tmp_path / "meta")


@pytest.fixture
def audit_log(tmp_path: Path) -> TenantAuditLog:
    return TenantAuditLog(tmp_path / "audit.jsonl")


def _read_audit(audit_log) -> list[dict]:
    if not audit_log.path.exists():
        return []
    out: list[dict] = []
    for line in audit_log.path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def test_phone_shaped_anon_id_is_rejected_by_pii_stage(meta_store, audit_log):
    """The collector must NOT land an envelope whose checker pipeline failed.

    THIS IS THE PRIVACY-LOAD-BEARING ASSERTION. If this flips to passing
    wrong (envelope lands despite the checker failing), the collector
    has dropped the gate.
    """

    cfg = TenantSignatureConfig(tenant_anon_id=PHONE_SHAPED_ANON_ID)
    collector = SignatureCollector(
        tenant_config=cfg,
        meta_store=meta_store,
        audit_log=audit_log,
    )

    raw = RawNamingConventionEvent(
        tenant_anon_id=PHONE_SHAPED_ANON_ID,
        applies_to="drawing_number",
        raw_template="<phase>-<discipline>",
        matched_count=10,
        sample_count=10,
    )
    result = _run(collector.process_one(raw))

    # Outcome must be CHECKER_REJECTED — not ACCEPTED.
    assert result.outcome == CollectorOutcome.CHECKER_REJECTED
    assert result.envelope is None

    # Meta store is empty — nothing crossed the boundary.
    assert _run(meta_store.count()) == 0

    # Audit log has exactly one entry with the privacy-safe shape.
    audit = _read_audit(audit_log)
    assert len(audit) == 1
    entry = audit[0]
    assert set(entry.keys()) == {"payload_hash", "reason_code", "stage", "timestamp"}
    assert entry["payload_hash"] == result.payload_hash
    # Reason is from the PII stage (regex layer caught phone-shape).
    assert entry["stage"] == Stage.PII_NER.value
    assert entry["reason_code"] in {
        ReasonCode.NER_HIT_PHONE.value,
        ReasonCode.NER_HIT_SSN.value,
    }


def test_audit_entry_does_not_carry_payload_bytes(meta_store, audit_log):
    """The raw event's tenant-side strings must not appear on disk."""

    cfg = TenantSignatureConfig(tenant_anon_id=PHONE_SHAPED_ANON_ID)
    collector = SignatureCollector(
        tenant_config=cfg,
        meta_store=meta_store,
        audit_log=audit_log,
    )

    raw = RawNamingConventionEvent(
        tenant_anon_id=PHONE_SHAPED_ANON_ID,
        applies_to="drawing_number",
        # An identifier that, if the audit log leaked, we'd recognize.
        raw_template="<DD>-<ELE>",
        matched_count=5,
        sample_count=5,
        example_identifiers=["SECRET-EXAMPLE-12345"],
    )
    _run(collector.process_one(raw))

    on_disk = audit_log.path.read_text(encoding="utf-8")
    assert "SECRET-EXAMPLE-12345" not in on_disk
    # Tenant-side template tokens must not leak either.
    assert "<DD>" not in on_disk


def test_blocked_event_does_not_increment_meta_store(meta_store, audit_log):
    """Many rejected events -> meta store stays at zero rows."""

    cfg = TenantSignatureConfig(tenant_anon_id=PHONE_SHAPED_ANON_ID)
    collector = SignatureCollector(
        tenant_config=cfg,
        meta_store=meta_store,
        audit_log=audit_log,
    )
    raw = RawNamingConventionEvent(
        tenant_anon_id=PHONE_SHAPED_ANON_ID,
        applies_to="drawing_number",
        raw_template="<DD>",
        matched_count=1,
        sample_count=1,
    )
    for _ in range(5):
        _run(collector.process_one(raw))

    assert _run(meta_store.count()) == 0
    assert len(_read_audit(audit_log)) == 5

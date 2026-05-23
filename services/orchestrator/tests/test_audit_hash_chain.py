"""AuditLog hash chain tests."""

from __future__ import annotations

import sqlite3

import pytest

from versawiki_orchestrator.audit import AuditLog, AuditLogVerifyError


def test_append_returns_entry_with_chain_hash(tmp_audit: AuditLog) -> None:
    e1 = tmp_audit.append("event_a", {"x": 1})
    assert e1.id == 1
    assert e1.prev_hash == "0" * 64
    assert len(e1.this_hash) == 64
    assert e1.event_type == "event_a"
    assert e1.payload == {"x": 1}


def test_chain_links_consecutive_rows(tmp_audit: AuditLog) -> None:
    e1 = tmp_audit.append("event_a", {"x": 1})
    e2 = tmp_audit.append("event_b", {"x": 2})
    e3 = tmp_audit.append("event_c", {"x": 3})

    assert e2.prev_hash == e1.this_hash
    assert e3.prev_hash == e2.this_hash
    # Different rows must produce different hashes (no payload collision).
    assert len({e1.this_hash, e2.this_hash, e3.this_hash}) == 3


def test_verify_passes_on_untampered_chain(tmp_audit: AuditLog) -> None:
    for i in range(20):
        tmp_audit.append("e", {"i": i})
    assert tmp_audit.verify() == 20


def test_verify_detects_payload_tampering(tmp_path) -> None:
    db = tmp_path / "audit.sqlite"
    log = AuditLog(db)
    log.append("e", {"x": 1})
    log.append("e", {"x": 2})
    log.close()

    # Tamper with row 1's payload directly via SQLite.
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE audit SET payload = ? WHERE id = 1", ('{"x":999}',))
    conn.commit()
    conn.close()

    log2 = AuditLog(db)
    try:
        with pytest.raises(AuditLogVerifyError):
            log2.verify()
    finally:
        log2.close()


def test_verify_detects_row_deletion(tmp_path) -> None:
    db = tmp_path / "audit.sqlite"
    log = AuditLog(db)
    log.append("e", {"x": 1})
    log.append("e", {"x": 2})
    log.append("e", {"x": 3})
    log.close()

    # Delete the middle row.
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM audit WHERE id = 2")
    conn.commit()
    conn.close()

    log2 = AuditLog(db)
    try:
        with pytest.raises(AuditLogVerifyError):
            log2.verify()
    finally:
        log2.close()


def test_tail_returns_most_recent_n(tmp_audit: AuditLog) -> None:
    for i in range(5):
        tmp_audit.append("e", {"i": i})
    tail = tmp_audit.tail(3)
    assert [e.payload["i"] for e in tail] == [2, 3, 4]


def test_count_filter_by_event_type(tmp_audit: AuditLog) -> None:
    for _ in range(3):
        tmp_audit.append("a", {})
    for _ in range(2):
        tmp_audit.append("b", {})
    assert tmp_audit.count() == 5
    assert tmp_audit.count("a") == 3
    assert tmp_audit.count("b") == 2
    assert tmp_audit.count("nope") == 0


def test_sum_payload_numeric(tmp_audit: AuditLog) -> None:
    tmp_audit.append("spend_recorded", {"amount_usd": 1.50})
    tmp_audit.append("spend_recorded", {"amount_usd": 2.25})
    tmp_audit.append("other", {"amount_usd": 999.0})  # should be excluded
    total = tmp_audit.sum_payload_numeric("spend_recorded", "amount_usd")
    assert total == pytest.approx(3.75)

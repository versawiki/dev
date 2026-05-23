"""Escalation queue tests — append-only, never modifies prior entries."""

from __future__ import annotations

import json
from pathlib import Path

from versawiki_support.escalation.queue import EscalationEntry, EscalationQueue


def _mk_entry(conv_id: str, severity: str = "low") -> EscalationEntry:
    return EscalationEntry(
        conversation_id=conv_id,
        tenant_id="t1",
        channel="web",
        reason="testing",
        severity=severity,  # type: ignore[arg-type]
        customer_identifier="cust@x.com",
    )


def test_append_creates_file(tmp_path: Path) -> None:
    q = EscalationQueue(tmp_path)
    path = q.append(_mk_entry("conv_a"))
    assert path.exists()
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["conversation_id"] == "conv_a"
    assert body["severity"] == "low"


def test_second_append_same_conv_does_not_overwrite(tmp_path: Path) -> None:
    q = EscalationQueue(tmp_path)
    p1 = q.append(_mk_entry("conv_a", severity="low"))
    p2 = q.append(_mk_entry("conv_a", severity="high"))
    assert p1 != p2
    assert p1.exists() and p2.exists()
    # Originals untouched
    assert json.loads(p1.read_text(encoding="utf-8"))["severity"] == "low"
    assert json.loads(p2.read_text(encoding="utf-8"))["severity"] == "high"


def test_list_all_returns_in_order(tmp_path: Path) -> None:
    q = EscalationQueue(tmp_path)
    q.append(_mk_entry("conv_a"))
    q.append(_mk_entry("conv_b"))
    q.append(_mk_entry("conv_c"))
    ids = [e.conversation_id for e in q.list_all()]
    assert set(ids) == {"conv_a", "conv_b", "conv_c"}


def test_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    q = EscalationQueue(tmp_path / "nope")
    assert q.list_all() == []


def test_entry_round_trip(tmp_path: Path) -> None:
    q = EscalationQueue(tmp_path)
    original = _mk_entry("conv_x", severity="high")
    q.append(original)
    entries = q.list_all()
    assert len(entries) == 1
    e = entries[0]
    assert e.conversation_id == original.conversation_id
    assert e.tenant_id == original.tenant_id
    assert e.severity == original.severity
    assert e.customer_identifier == original.customer_identifier
    assert e.reason == original.reason


def test_buckets_by_date(tmp_path: Path) -> None:
    q = EscalationQueue(tmp_path)
    q.append(_mk_entry("conv_a"))
    # All entries today => exactly one date bucket
    subdirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(subdirs) == 1
    # YYYY-MM-DD format
    assert len(subdirs[0].name) == 10
    assert subdirs[0].name.count("-") == 2

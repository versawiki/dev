"""TenantAuditLog — JSONL writer for rejected events.

The single most important assertion in this file is the *privacy
invariant*: the on-disk record contains payload_hash + reason_code +
stage + timestamp ONLY. No portion of the offending payload appears.

If a future change to `TenantAuditLog.write` introduces a `payload`,
`details`, or `errors` field, the assertion `set(record.keys()) ==
{...}` below fails. That is the early-warning system for this class
of regression.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from versawiki_meta_mcp.audit import TenantAuditLog
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage


_ALLOWED_RECORD_KEYS = {"payload_hash", "reason_code", "stage", "timestamp"}


def _read_lines(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_write_creates_jsonl_record(audit_path):
    log = TenantAuditLog(audit_path)
    log.write(
        payload_hash="a" * 64,
        reason_code=ReasonCode.FORBIDDEN_FIELD_NAME,
        stage=Stage.FORBIDDEN_FIELD_NAME_SCAN,
    )

    records = _read_lines(audit_path)
    assert len(records) == 1

    rec = records[0]
    assert rec["payload_hash"] == "a" * 64
    assert rec["reason_code"] == "FORBIDDEN_FIELD_NAME"
    assert rec["stage"] == "forbidden_field_name_scan"
    assert "timestamp" in rec and rec["timestamp"].startswith("20")  # ISO-8601


def test_write_never_includes_payload_bytes(audit_path):
    """*** PRIVACY INVARIANT — load-bearing assertion ***

    Whatever fields end up in the record, the SET of field names must be
    exactly {payload_hash, reason_code, stage, timestamp}. No field that
    could carry payload bytes (payload, details, errors, body, ...) is
    permitted. If this fails, a checker or audit writer regressed.
    """

    log = TenantAuditLog(audit_path)
    fake_pii = "john.doe@example.com"
    fake_hash = "deadbeef" * 8  # 64-hex sha256-shaped
    log.write(
        payload_hash=fake_hash,
        reason_code=ReasonCode.NER_HIT_EMAIL,
        stage=Stage.PII_NER,
    )

    records = _read_lines(audit_path)
    assert len(records) == 1
    rec = records[0]

    # ⚠ DO NOT LOOSEN — see module docstring.
    assert set(rec.keys()) == _ALLOWED_RECORD_KEYS, (
        f"audit record has unexpected keys: {set(rec.keys()) - _ALLOWED_RECORD_KEYS}"
    )

    # And explicitly: the email string should not appear *anywhere* in
    # the on-disk bytes. (Read the raw file too, not just parsed JSON,
    # because JSON encoding could in principle stash bytes in a comment
    # field; JSONL has no comments but belt-and-braces.)
    raw = audit_path.read_text(encoding="utf-8")
    assert fake_pii not in raw


def test_write_is_append_only(audit_path):
    """Two `write` calls produce two lines; the first is untouched."""

    log = TenantAuditLog(audit_path)
    log.write(
        payload_hash="1" * 64,
        reason_code=ReasonCode.FORBIDDEN_FIELD_NAME,
        stage=Stage.FORBIDDEN_FIELD_NAME_SCAN,
    )
    log.write(
        payload_hash="2" * 64,
        reason_code=ReasonCode.RAW_NUMERIC,
        stage=Stage.NUMERIC_PATTERN,
    )

    records = _read_lines(audit_path)
    assert len(records) == 2
    assert records[0]["payload_hash"] == "1" * 64
    assert records[0]["reason_code"] == "FORBIDDEN_FIELD_NAME"
    assert records[1]["payload_hash"] == "2" * 64
    assert records[1]["reason_code"] == "RAW_NUMERIC"


def test_write_accepts_stage_as_plain_string(audit_path):
    """For forward-compat with v2's stage field that might come from a
    different source, plain strings should be accepted."""

    log = TenantAuditLog(audit_path)
    log.write(
        payload_hash="c" * 64,
        reason_code=ReasonCode.OPT_OUT,
        stage="opt_out_gate",
    )
    records = _read_lines(audit_path)
    assert records[0]["stage"] == "opt_out_gate"


def test_path_property_reports_target_file(audit_path):
    log = TenantAuditLog(audit_path)
    assert Path(log.path) == audit_path

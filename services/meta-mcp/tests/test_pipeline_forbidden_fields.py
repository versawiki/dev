"""Stage 2 — forbidden-field-name scan.

Because the envelope's `extra="forbid"` strips unknown keys at stage 1,
the forbidden-field stage is a defense-in-depth invariant audit. We
exercise it primarily at the unit level — feeding the stage hand-crafted
dicts that simulate the schema drift / dynamically-constructed payload
case the stage exists to catch.

The names exercised here are drawn from spec §4 and are present in
`forbidden_fields.FORBIDDEN_FIELD_NAMES`.
"""

from __future__ import annotations

import pytest

from versawiki_meta_mcp.checkers.forbidden_fields import (
    FORBIDDEN_FIELD_NAMES,
    FORBIDDEN_FIELD_PREFIXES,
    scan_forbidden_field_names,
)
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage


@pytest.mark.parametrize(
    "forbidden_key",
    ["name", "title", "file_path", "raw_text", "description", "email", "phone"],
)
def test_forbidden_top_level_field_caught(forbidden_key):
    """A forbidden field name at any depth fires the stage. Top-level case."""

    obj = {forbidden_key: "anything"}
    result = scan_forbidden_field_names(obj)
    assert not result.passed
    assert result.stage == Stage.FORBIDDEN_FIELD_NAME_SCAN
    assert result.reason_code == ReasonCode.FORBIDDEN_FIELD_NAME
    assert forbidden_key in result.details


def test_forbidden_nested_field_caught():
    """The §4 blocklist applies at *any* depth. Deep nesting must still trip."""

    obj = {
        "payload": {
            "subsection": {
                "rows": [
                    {"file_path": "/etc/passwd"},
                ]
            }
        }
    }
    result = scan_forbidden_field_names(obj)
    assert not result.passed
    assert result.reason_code == ReasonCode.FORBIDDEN_FIELD_NAME
    assert "file_path" in result.details


def test_forbidden_field_case_insensitive():
    """Per the task brief and the source comment, matching is case-insensitive."""

    obj = {"Title": "Whatever"}
    result = scan_forbidden_field_names(obj)
    assert not result.passed
    assert result.reason_code == ReasonCode.FORBIDDEN_FIELD_NAME


@pytest.mark.parametrize("prefix", list(FORBIDDEN_FIELD_PREFIXES))
def test_forbidden_field_prefix_caught(prefix):
    """`measurement_*` and `dim_*` prefixes are blocked under spec §4."""

    obj = {f"{prefix}widget": 12}
    result = scan_forbidden_field_names(obj)
    assert not result.passed
    assert result.reason_code == ReasonCode.FORBIDDEN_FIELD_NAME


def test_clean_payload_passes():
    """Schema-conformant dicts with no forbidden keys pass."""

    obj = {
        "payload": {
            "kind": "ontology_shape",
            "depth": 4,
            "node_count_bucket": "51-200",
            "kind_distribution": {"category": 1, "entity": 2, "topic": 3},
        }
    }
    result = scan_forbidden_field_names(obj)
    assert result.passed


def test_forbidden_field_names_contains_spec_section_4_entries():
    """Sanity-check: spec §4 mandates these forbidden names. Missing one
    here is a silent privacy bug. (See top of `notes/mcp-builder.md`.)"""

    must_have = {
        "raw_text", "excerpt", "snippet", "body", "content",
        "file_path", "file_name", "filename", "source_uri", "blob_key", "path",
        "tenant_slug", "tenant_name", "display_name", "customer_name",
        "project_name", "org_name", "vendor_name", "person_name",
        "email", "phone",
        "count", "total", "revenue", "value", "amount", "headcount", "quantity",
        "title", "name", "label", "description",
        "query_text", "query", "q",
    }
    assert must_have <= FORBIDDEN_FIELD_NAMES, (
        f"missing from FORBIDDEN_FIELD_NAMES: {must_have - FORBIDDEN_FIELD_NAMES}"
    )

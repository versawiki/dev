"""Shared pytest fixtures for the meta-MCP test suite.

The fixtures here build *valid, principle-only* envelopes plus deliberately
tainted variants. Keep these payloads in sync with
`docs/architecture/domain-observation-v1.md` — when the spec adds a payload
variant, mirror it here.

No fixture should ever pretend to be a real customer. The data here is
shape only.

Note on `event_id`: we deliberately use a fixed, hex-letter-heavy UUID
string instead of `uuid.uuid4()`. Random UUIDv4s occasionally contain
phone-shaped digit runs (3-3-4) that trip the PII regex layer ~3% of
the time. That's a separate over-eager-regex issue tracked in
`notes/mcp-builder.md`; using a deterministic safe value keeps test
runs reproducible.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


# Hex-letter-heavy UUID shape that does not contain any 3-3-4 digit run.
_SAFE_EVENT_ID = "abcdefab-cdef-4abc-9abc-abcdefabcdef"
_SAFE_TENANT_ANON_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_audit_dir(tmp_path: Path) -> Path:
    """A scratch tenant-directory in which audit.jsonl will be created."""

    d = tmp_path / "tenant_dir"
    d.mkdir()
    return d


@pytest.fixture
def audit_path(tmp_audit_dir: Path) -> Path:
    return tmp_audit_dir / "audit.jsonl"


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------


def _base_envelope(payload: dict[str, Any], *, opt_out: bool = False) -> dict[str, Any]:
    return {
        "event_id": _SAFE_EVENT_ID,
        "schema_version": "1.0.0",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        # 36-char UUID-shape per spec §2.1; passes PII regex layer.
        "tenant_anon_id": _SAFE_TENANT_ANON_ID,
        "opt_out_flag": opt_out,
        "domain_signature_id": None,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Principle-only payloads — these MUST pass all stages.
# ---------------------------------------------------------------------------


@pytest.fixture
def payload_ontology_shape() -> dict[str, Any]:
    return {
        "kind": "ontology_shape",
        "depth": 4,
        "node_count_bucket": "51-200",
        # Per spec §3.1, branching factors are real-valued shape statistics,
        # not ratios or probabilities; values > 1 are normal for real trees.
        "branching_factor_p50": 2.5,
        "branching_factor_p95": 7.0,
        "leaf_to_internal_ratio": 0.75,
        "kind_distribution": {"category": 12, "entity": 30, "topic": 8},
        "induced_vs_seed_ratio": 0.4,
    }


@pytest.fixture
def payload_naming_convention() -> dict[str, Any]:
    return {
        "kind": "naming_convention",
        "applies_to": "drawing_number",
        "template": "<phase>-<discipline>-<sequence>",
        "token_vocabulary": ["phase", "discipline", "sequence"],
        "sample_count_bucket": "51-200",
        "adherence_rate": 0.93,
    }


@pytest.fixture
def payload_document_type_distribution() -> dict[str, Any]:
    return {
        "kind": "document_type_distribution",
        "generic_type_counts": {
            "drawing": "201-1000",
            "specification": "11-50",
            "rfi": "51-200",
            "submittal": "11-50",
            "meeting_minutes": "1-10",
            "report": "1-10",
            "calculation": "1-10",
            "contract": "1-10",
            "correspondence": "11-50",
            "schedule": "1-10",
            "image": "1-10",
            "spreadsheet": "1-10",
            "presentation": "0",
            "other": "0",
        },
        "total_documents_bucket": "201-1000",
        "classifier_confidence_p50": 0.88,
        "classifier_confidence_p10": 0.55,
    }


@pytest.fixture
def payload_relationship_schema() -> dict[str, Any]:
    return {
        "kind": "relationship_schema",
        "edges": [
            {
                "source_type": "drawing",
                "target_type": "specification",
                "relation": "references",
                "detection_method": "label_pattern",
                "edge_count_bucket": "101-1000",
                "confidence_p50": 0.82,
            },
            {
                "source_type": "rfi",
                "target_type": "drawing",
                "relation": "responds_to",
                "detection_method": "explicit_field",
                "edge_count_bucket": "11-100",
                "confidence_p50": 0.95,
            },
        ],
    }


@pytest.fixture
def payload_procedure_pattern() -> dict[str, Any]:
    return {
        "kind": "procedure_pattern",
        "applies_to_type": "rfi",
        "states": ["open", "responded", "closed"],
        "transitions_observed_bucket": "101-1000",
        "median_lifecycle_states": 3,
        "detection_method": "revision_metadata",
    }


@pytest.fixture
def payload_query_pattern_shape() -> dict[str, Any]:
    return {
        "kind": "query_pattern_shape",
        "shape_template": "find <type> by <identifier_kind>",
        "token_vocabulary": ["type", "identifier_kind"],
        "occurrence_count_bucket": "51-200",
        "caller_kind": "human",
    }


@pytest.fixture
def payload_classifier_uncertainty() -> dict[str, Any]:
    return {
        "kind": "classifier_uncertainty",
        "uncertain_pairs": [
            {"type_a": "drawing", "type_b": "calculation", "confusion_rate": 0.15},
            {"type_a": "rfi", "type_b": "submittal", "confusion_rate": 0.08},
        ],
        "overall_confidence_p10": 0.62,
        "sampled_documents_bucket": "101-1000",
    }


@pytest.fixture
def payload_ingestion_pipeline_metrics() -> dict[str, Any]:
    return {
        "kind": "ingestion_pipeline_metrics",
        "chunker_strategy": "semantic",
        "embedding_provider_family": "openai",
        "embedding_dim": 1024,
        "docs_processed_bucket": "101-1000",
        "chunks_per_doc_p50": 8,
        "chunks_per_doc_p95": 42,
        "classification_failure_rate": 0.04,
        "ontology_assignment_failure_rate": 0.11,
    }


# ---------------------------------------------------------------------------
# Envelope builder helper exposed to tests
# ---------------------------------------------------------------------------


@pytest.fixture
def envelope_of():
    """Return a callable: payload-dict -> envelope-dict (opt_out=False)."""

    def _build(payload: dict[str, Any], *, opt_out: bool = False) -> dict[str, Any]:
        return _base_envelope(payload, opt_out=opt_out)

    return _build


# ---------------------------------------------------------------------------
# Convenient envelopes for the happy-path tests.
# ---------------------------------------------------------------------------


@pytest.fixture
def all_principle_payloads(
    payload_ontology_shape,
    payload_naming_convention,
    payload_document_type_distribution,
    payload_relationship_schema,
    payload_procedure_pattern,
    payload_query_pattern_shape,
    payload_classifier_uncertainty,
    payload_ingestion_pipeline_metrics,
) -> list[dict[str, Any]]:
    """All 8 payloads, each principle-only."""

    return [
        payload_ontology_shape,
        payload_naming_convention,
        payload_document_type_distribution,
        payload_relationship_schema,
        payload_procedure_pattern,
        payload_query_pattern_shape,
        payload_classifier_uncertainty,
        payload_ingestion_pipeline_metrics,
    ]

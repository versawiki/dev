"""Stage 4 — numeric-pattern detector.

The schema's `Field(ge=, le=)` discipline catches *most* numeric violations
at stage 1, so this test exercises numerics that pass the schema but
violate the numeric-stage's stricter band:

  * ratio leaves must be in [0,1]
  * structural-count leaves must be int in [0, STRUCTURAL_COUNT_MAX)
  * dict[Literal, int] values must be in [0, STRUCTURAL_COUNT_MAX)
"""

from __future__ import annotations

import pytest

from versawiki_meta_mcp.checkers.numeric import (
    STRUCTURAL_COUNT_MAX,
    scan_numeric_pattern,
)
from versawiki_meta_mcp.checkers.pipeline import CheckerPipeline
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage


def test_raw_count_under_kind_distribution_rejected(envelope_of):
    """A raw count >= 1000 under `kind_distribution` (a controlled-key dict
    where the schema allows int values) is rejected by stage 4 with
    RAW_NUMERIC. The forbidden-field stage cannot catch this — the key is
    a `Literal` vocabulary member, not the field name `count`.
    """

    env = envelope_of(
        {
            "kind": "ontology_shape",
            "depth": 4,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 0.5,
            "branching_factor_p95": 0.7,
            "leaf_to_internal_ratio": 0.75,
            "kind_distribution": {"category": 4732, "entity": 30, "topic": 8},
            "induced_vs_seed_ratio": 0.4,
        }
    )
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert r.failed_stage == Stage.NUMERIC_PATTERN
    assert r.failed_reason == ReasonCode.RAW_NUMERIC


def test_structural_count_above_max_rejected(envelope_of):
    """`chunks_per_doc_p50` is schema-allowed up to 10000 but the numeric
    stage requires < STRUCTURAL_COUNT_MAX (1000). The stage exists exactly
    to catch schemas that drift out of the privacy-safe band.
    """

    env = envelope_of(
        {
            "kind": "ingestion_pipeline_metrics",
            "chunker_strategy": "semantic",
            "embedding_provider_family": "openai",
            "embedding_dim": 1024,
            "docs_processed_bucket": "101-1000",
            "chunks_per_doc_p50": 1500,
            "chunks_per_doc_p95": 42,
            "classification_failure_rate": 0.04,
            "ontology_assignment_failure_rate": 0.11,
        }
    )
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert r.failed_stage == Stage.NUMERIC_PATTERN
    assert r.failed_reason == ReasonCode.RAW_NUMERIC


def test_ratio_out_of_range_rejected(envelope_of):
    """`leaf_to_internal_ratio` is in ALLOWED_RATIO_LEAVES; > 1.0 is RAW_NUMERIC.

    Note: branching_factor_p50/p95 are NOT ratio leaves (see spec §3.1 and
    ALLOWED_BRANCHING_FACTOR_LEAVES in numeric.py) — they may legitimately
    exceed 1.0.  This test uses `leaf_to_internal_ratio` as the offending field.
    """

    env = envelope_of(
        {
            "kind": "ontology_shape",
            "depth": 4,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 3.0,   # valid branching factor (> 1 is fine)
            "branching_factor_p95": 7.0,   # valid branching factor
            "leaf_to_internal_ratio": 2.5,  # > 1.0 for a ratio → RAW_NUMERIC
            "kind_distribution": {"category": 12, "entity": 30, "topic": 8},
            "induced_vs_seed_ratio": 0.4,
        }
    )
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert r.failed_stage == Stage.NUMERIC_PATTERN
    assert r.failed_reason == ReasonCode.RAW_NUMERIC


def test_bucket_labels_and_ratios_pass_numeric_stage(
    envelope_of, payload_ingestion_pipeline_metrics
):
    """Bucket-string labels are not numeric leaves and trivially pass;
    ratios in [0,1] pass; structural counts under STRUCTURAL_COUNT_MAX pass.
    """

    env = envelope_of(payload_ingestion_pipeline_metrics)
    r = CheckerPipeline().check(env)
    assert r.passed
    stage_results = {res.stage: res for res in r.results}
    assert stage_results[Stage.NUMERIC_PATTERN].passed


def test_scan_numeric_pattern_unit_pass():
    """Direct invocation of the stage on a synthesized walked dict."""

    safe = {
        "payload": {
            "depth": 4,
            "branching_factor_p50": 0.5,
            "kind_distribution": {"category": 12, "entity": 30, "topic": 8},
            "embedding_dim": 1024,  # Literal[1024]; pass even though >MAX
        }
    }
    result = scan_numeric_pattern(safe)
    assert result.passed


def test_scan_numeric_pattern_unit_unknown_numeric_leaf():
    """An unanticipated numeric leaf fails RAW_NUMERIC."""

    bad = {"payload": {"some_unexpected_count": 12}}
    result = scan_numeric_pattern(bad)
    assert not result.passed
    assert result.reason_code == ReasonCode.RAW_NUMERIC


def test_structural_count_max_constant_is_1000():
    """Sanity check — the privacy-safe band is exactly < 1000 per spec §5.2."""

    assert STRUCTURAL_COUNT_MAX == 1000


def test_branching_factor_above_one_should_pass(envelope_of):
    """Per spec §3.1, branching factor is a real-valued statistic, not a
    ratio. A tree with branching factor 2.5 is principle-only data and must
    pass the numeric stage. branching_factor_p50/p95 live in
    ALLOWED_BRANCHING_FACTOR_LEAVES (not ALLOWED_RATIO_LEAVES) and are
    capped only at STRUCTURAL_COUNT_MAX, not at 1.0."""

    env = envelope_of(
        {
            "kind": "ontology_shape",
            "depth": 4,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 2.5,
            "branching_factor_p95": 7.0,
            "leaf_to_internal_ratio": 0.75,
            "kind_distribution": {"category": 12, "entity": 30, "topic": 8},
            "induced_vs_seed_ratio": 0.4,
        }
    )
    r = CheckerPipeline().check(env)
    assert r.passed, (
        f"branching factor 2.5 should pass; failed at "
        f"{r.failed_stage}/{r.failed_reason}"
    )

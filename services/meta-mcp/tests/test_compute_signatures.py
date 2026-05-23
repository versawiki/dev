"""Unit tests for the eight `compute_<variant>` functions.

Boundary-value bucket tests, ratio clamping, deterministic vocabulary
mapping. These are the lowest-level signature unit tests; the
collector-level happy-path test layers on top.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from versawiki_meta_mcp.collector.signatures import (
    compute_classifier_uncertainty,
    compute_document_type_distribution,
    compute_ingestion_pipeline_metrics,
    compute_naming_convention,
    compute_ontology_shape,
    compute_procedure_pattern,
    compute_query_pattern_shape,
    compute_relationship_schema,
)
from versawiki_meta_mcp.collector.tenant_config import (
    DEFAULT_BUCKETS,
    TenantSignatureConfig,
    name_bucket,
)
from versawiki_meta_mcp.events.raw_event import (
    RawClassifierUncertaintyEvent,
    RawDocumentTypeDistributionEvent,
    RawIngestionPipelineMetricsEvent,
    RawNamingConventionEvent,
    RawOntologyShapeEvent,
    RawProcedurePatternEvent,
    RawQueryPatternShapeEvent,
    RawRelationshipEdgeObservation,
    RawRelationshipSchemaEvent,
    RawUncertainPairObservation,
)


SAFE_ANON_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


@pytest.fixture
def tenant_config() -> TenantSignatureConfig:
    """Tenant config with the AEC starter mapping."""

    return TenantSignatureConfig(
        tenant_anon_id=SAFE_ANON_ID,
        opt_out=False,
        type_vocab={
            "Drawing": "drawing",
            "Spec": "specification",
            "RFI": "rfi",
        },
        relation_type_vocab={
            "Drawing": "drawing",
            "Spec": "specification",
            "RFI": "rfi",
            "Submittal": "submittal",
            "Calculation": "calculation",
        },
        procedure_type_vocab={
            "RFI": "rfi",
            "Drawing": "drawing",
        },
        naming_token_vocab={
            "DD": "phase",
            "ELE": "discipline",
            "NNN": "sequence",
        },
        query_token_vocab={
            "doctype": "type",
            "idkind": "identifier_kind",
        },
        state_vocab={
            "Open": "open",
            "Responded": "responded",
            "Closed": "closed",
        },
    )


# ---------------------------------------------------------------------------
# Bucket boundary unit tests (independent of any compute_*)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "1-10"),
        (1, "1-10"),
        (10, "1-10"),
        (11, "11-50"),
        (50, "11-50"),
        (51, "51-200"),
        (200, "51-200"),
        (201, "201-1000"),
        (1000, "201-1000"),
        (1001, "1000+"),
        (1_000_000, "1000+"),
    ],
)
def test_count_10_1000plus_buckets_boundary_values(value, expected):
    assert name_bucket(value, DEFAULT_BUCKETS.count_10_1000plus) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0"),
        (1, "1-10"),
        (10, "1-10"),
        (11, "11-50"),
        (200, "51-200"),
        (1001, "1000+"),
    ],
)
def test_per_type_buckets_boundary_values(value, expected):
    assert name_bucket(value, DEFAULT_BUCKETS.per_type) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (1, "1-10"),
        (10, "1-10"),
        (11, "11-100"),
        (100, "11-100"),
        (101, "101-1000"),
        (1000, "101-1000"),
        (1001, "1000+"),
    ],
)
def test_edge_count_buckets_boundary_values(value, expected):
    assert name_bucket(value, DEFAULT_BUCKETS.edge_count) == expected


def test_negative_count_raises_value_error():
    with pytest.raises(ValueError):
        name_bucket(-1, DEFAULT_BUCKETS.count_10_1000plus)


# ---------------------------------------------------------------------------
# 3.1 — OntologyShape
# ---------------------------------------------------------------------------


def test_compute_ontology_shape_buckets_correctly(tenant_config):
    raw = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID,
        depth=5,
        node_count=75,
        branching_factors=[0.0, 0.0, 0.5, 0.7, 0.9, 0.4, 0.0],
        kind_distribution={"category": 10, "entity": 30, "topic": 5},
        node_labels=["Project A", "Contract Foo"],  # never crosses
        induced_node_count=8,
        seed_node_count=12,
    )
    out = compute_ontology_shape(raw, tenant_config)
    assert out.node_count_bucket == "51-200"
    # branching factors are structural shape stats (spec §3.1), not ratios —
    # they are non-negative reals that may exceed 1.0.
    assert out.branching_factor_p50 >= 0.0
    assert out.branching_factor_p95 >= 0.0
    assert 0.0 <= out.leaf_to_internal_ratio <= 1.0
    assert out.induced_vs_seed_ratio == pytest.approx(8 / 20)
    assert out.kind_distribution == {"category": 10, "entity": 30, "topic": 5}


def test_compute_ontology_shape_no_induction_input(tenant_config):
    raw = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID,
        depth=3,
        node_count=12,
        branching_factors=[0.2, 0.3],
        kind_distribution={"category": 5},
    )
    out = compute_ontology_shape(raw, tenant_config)
    assert out.induced_vs_seed_ratio is None
    assert out.node_count_bucket == "11-50"


def test_compute_ontology_shape_branching_factor_above_one_preserved(tenant_config):
    """Branching factors > 1.0 must NOT be clamped by compute_ontology_shape.

    Per spec §3.1, branching_factor_p50/p95 are structural tree-shape
    statistics (average children per node), not probabilities. A node with
    3 children has branching factor 3 — legitimate principle-only data.
    The collector previously called _clamp01(), silently discarding real
    signal.  This test pins the correct behaviour end-to-end.
    """
    raw = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID,
        depth=4,
        node_count=100,
        branching_factors=[1.5, 2.0, 3.0, 4.5, 7.0, 2.5, 3.5],
        kind_distribution={"category": 10, "entity": 20, "topic": 5},
    )
    out = compute_ontology_shape(raw, tenant_config)
    # Median (p50) of sorted [1.5, 2.0, 2.5, 3.0, 3.5, 4.5, 7.0] = 3.0.
    # p95 of 7 values = 7.0.  Both must survive > 1.0.
    assert out.branching_factor_p50 > 1.0, (
        f"branching_factor_p50 was clamped: got {out.branching_factor_p50}"
    )
    assert out.branching_factor_p95 > 1.0, (
        f"branching_factor_p95 was clamped: got {out.branching_factor_p95}"
    )


# ---------------------------------------------------------------------------
# 3.2 — NamingConvention
# ---------------------------------------------------------------------------


def test_compute_naming_convention_rewrites_tenant_tokens(tenant_config):
    raw = RawNamingConventionEvent(
        tenant_anon_id=SAFE_ANON_ID,
        applies_to="drawing_number",
        raw_template="<DD>-<ELE>-<NNN>",
        matched_count=93,
        sample_count=100,
        example_identifiers=["DD-ELE-001", "DD-ELE-002"],
    )
    out = compute_naming_convention(raw, tenant_config)
    assert out.template == "<phase>-<discipline>-<sequence>"
    assert out.token_vocabulary == ["phase", "discipline", "sequence"]
    assert out.adherence_rate == pytest.approx(0.93)
    assert out.sample_count_bucket == "51-200"


def test_compute_naming_convention_unmapped_token_becomes_other(tenant_config):
    raw = RawNamingConventionEvent(
        tenant_anon_id=SAFE_ANON_ID,
        applies_to="document_id",
        raw_template="<ZZ_UNKNOWN>-<NNN>",
        matched_count=5,
        sample_count=5,
    )
    out = compute_naming_convention(raw, tenant_config)
    assert "<other>" in out.template
    assert "other" in out.token_vocabulary


def test_compute_naming_convention_deterministic(tenant_config):
    """Same raw event + same tenant config -> same envelope payload."""

    raw = RawNamingConventionEvent(
        tenant_anon_id=SAFE_ANON_ID,
        applies_to="drawing_number",
        raw_template="<DD>-<ELE>-<NNN>",
        matched_count=50,
        sample_count=51,
    )
    a = compute_naming_convention(raw, tenant_config)
    b = compute_naming_convention(raw, tenant_config)
    assert a.model_dump() == b.model_dump()


def test_compute_naming_convention_low_sample_bucket(tenant_config):
    """sample_count below the bucket floor (3) should pin to the smallest bucket."""

    raw = RawNamingConventionEvent(
        tenant_anon_id=SAFE_ANON_ID,
        applies_to="drawing_number",
        raw_template="<DD>",
        matched_count=1,
        sample_count=1,
    )
    out = compute_naming_convention(raw, tenant_config)
    assert out.sample_count_bucket == "3-10"


# ---------------------------------------------------------------------------
# 3.3 — DocumentTypeDistribution
# ---------------------------------------------------------------------------


def test_compute_doc_type_distribution_maps_and_buckets(tenant_config):
    raw = RawDocumentTypeDistributionEvent(
        tenant_anon_id=SAFE_ANON_ID,
        tenant_type_counts={
            "Drawing": 75,
            "Spec": 30,
            "RFI": 12,
            "UnknownClass": 4,
        },
        total_documents=121,
        classifier_confidences=[0.5, 0.7, 0.8, 0.85, 0.9, 0.92, 0.95, 0.99, 0.6, 0.55],
    )
    out = compute_doc_type_distribution_call(raw, tenant_config)
    assert out.generic_type_counts["drawing"] == "51-200"
    assert out.generic_type_counts["specification"] == "11-50"
    assert out.generic_type_counts["rfi"] == "11-50"
    # UnknownClass -> other
    assert out.generic_type_counts["other"] == "1-10"
    assert out.total_documents_bucket == "51-200"
    assert 0.0 <= out.classifier_confidence_p10 <= 1.0
    assert 0.0 <= out.classifier_confidence_p50 <= 1.0


def compute_doc_type_distribution_call(raw, tenant_config):
    """Wrapper just to keep the parametrized names short."""

    return compute_document_type_distribution(raw, tenant_config)


def test_compute_doc_type_distribution_sums_aliased_types(tenant_config):
    """Two tenant labels mapping to the same generic type combine counts."""

    cfg = tenant_config.model_copy(
        update={"type_vocab": {**tenant_config.type_vocab, "RFI Form": "rfi"}}
    )
    raw = RawDocumentTypeDistributionEvent(
        tenant_anon_id=SAFE_ANON_ID,
        tenant_type_counts={"RFI": 30, "RFI Form": 30},
        total_documents=60,
        classifier_confidences=[0.9],
    )
    out = compute_document_type_distribution(raw, cfg)
    assert out.generic_type_counts["rfi"] == "51-200"


# ---------------------------------------------------------------------------
# 3.4 — RelationshipSchema
# ---------------------------------------------------------------------------


def test_compute_relationship_schema_drops_zero_count_edges(tenant_config):
    raw = RawRelationshipSchemaEvent(
        tenant_anon_id=SAFE_ANON_ID,
        edges=[
            RawRelationshipEdgeObservation(
                source_tenant_type="Drawing",
                target_tenant_type="Spec",
                relation="references",
                detection_method="label_pattern",
                edge_count=42,
                confidences=[0.7, 0.8, 0.9],
            ),
            RawRelationshipEdgeObservation(
                source_tenant_type="Drawing",
                target_tenant_type="Spec",
                relation="supersedes",
                detection_method="explicit_field",
                edge_count=0,  # dropped
                confidences=[0.99],
            ),
        ],
    )
    out = compute_relationship_schema(raw, tenant_config)
    assert len(out.edges) == 1
    assert out.edges[0].source_type == "drawing"
    assert out.edges[0].target_type == "specification"
    assert out.edges[0].edge_count_bucket == "11-100"
    assert out.edges[0].confidence_p50 == pytest.approx(0.8)


def test_compute_relationship_schema_unknown_type_to_other(tenant_config):
    raw = RawRelationshipSchemaEvent(
        tenant_anon_id=SAFE_ANON_ID,
        edges=[
            RawRelationshipEdgeObservation(
                source_tenant_type="MystifyingThing",
                target_tenant_type="Drawing",
                relation="references",
                detection_method="label_pattern",
                edge_count=5,
                confidences=[0.5],
            ),
        ],
    )
    out = compute_relationship_schema(raw, tenant_config)
    assert out.edges[0].source_type == "other"
    assert out.edges[0].target_type == "drawing"


# ---------------------------------------------------------------------------
# 3.5 — ProcedurePattern
# ---------------------------------------------------------------------------


def test_compute_procedure_pattern_maps_states_and_bucket(tenant_config):
    raw = RawProcedurePatternEvent(
        tenant_anon_id=SAFE_ANON_ID,
        applies_to_tenant_type="RFI",
        tenant_states=["Open", "Responded", "Closed", "Open"],
        transitions_observed=150,
        lifecycle_state_counts=[3, 3, 3, 4, 2, 3],
        detection_method="revision_metadata",
    )
    out = compute_procedure_pattern(raw, tenant_config)
    assert out.applies_to_type == "rfi"
    assert out.states == ["open", "responded", "closed"]  # dedup + order preserved
    assert out.transitions_observed_bucket == "101-1000"
    assert out.median_lifecycle_states == 3


def test_compute_procedure_pattern_unknown_type_to_other(tenant_config):
    raw = RawProcedurePatternEvent(
        tenant_anon_id=SAFE_ANON_ID,
        applies_to_tenant_type="UnknownFlow",
        tenant_states=["Open"],
        transitions_observed=5,
        lifecycle_state_counts=[1, 2],
        detection_method="llm_extraction",
    )
    out = compute_procedure_pattern(raw, tenant_config)
    assert out.applies_to_type == "other"


# ---------------------------------------------------------------------------
# 3.6 — QueryPatternShape
# ---------------------------------------------------------------------------


def test_compute_query_pattern_shape_canonicalizes_template(tenant_config):
    raw = RawQueryPatternShapeEvent(
        tenant_anon_id=SAFE_ANON_ID,
        raw_template="find <doctype> by <idkind>",
        occurrence_count=75,
        caller_kind="human",
        raw_query_strings=[
            "find drawing by id E-101",
            "find spec by id 09 2900",
        ],
    )
    out = compute_query_pattern_shape(raw, tenant_config)
    assert out.shape_template == "find <type> by <identifier_kind>"
    assert out.token_vocabulary == ["type", "identifier_kind"]
    assert out.occurrence_count_bucket == "51-200"
    assert out.caller_kind == "human"


# ---------------------------------------------------------------------------
# 3.7 — ClassifierUncertainty
# ---------------------------------------------------------------------------


def test_compute_classifier_uncertainty_ratios_in_range(tenant_config):
    raw = RawClassifierUncertaintyEvent(
        tenant_anon_id=SAFE_ANON_ID,
        uncertain_pairs=[
            RawUncertainPairObservation(
                tenant_type_a="Drawing",
                tenant_type_b="Calculation",
                confused_count=15,
                total_count=100,
            ),
            RawUncertainPairObservation(
                tenant_type_a="RFI",
                tenant_type_b="Submittal",
                confused_count=8,
                total_count=100,
            ),
        ],
        overall_confidences=[0.5, 0.6, 0.7, 0.8, 0.9, 0.62],
        sampled_documents=250,
    )
    out = compute_classifier_uncertainty(raw, tenant_config)
    assert all(0.0 <= p.confusion_rate <= 1.0 for p in out.uncertain_pairs)
    assert 0.0 <= out.overall_confidence_p10 <= 1.0
    assert out.sampled_documents_bucket == "101-1000"


def test_compute_classifier_uncertainty_drops_degenerate_pair(tenant_config):
    """If both sides resolve to the same type, the pair is degenerate."""

    raw = RawClassifierUncertaintyEvent(
        tenant_anon_id=SAFE_ANON_ID,
        uncertain_pairs=[
            RawUncertainPairObservation(
                tenant_type_a="Drawing",
                tenant_type_b="Drawing",
                confused_count=5,
                total_count=10,
            ),
        ],
        overall_confidences=[0.5],
        sampled_documents=10,
    )
    out = compute_classifier_uncertainty(raw, tenant_config)
    assert out.uncertain_pairs == []


def test_compute_classifier_uncertainty_zero_total_safe(tenant_config):
    """confused_count/total_count with total=0 returns 0.0, not a div-by-zero."""

    raw = RawClassifierUncertaintyEvent(
        tenant_anon_id=SAFE_ANON_ID,
        uncertain_pairs=[
            RawUncertainPairObservation(
                tenant_type_a="Drawing",
                tenant_type_b="Spec",
                confused_count=0,
                total_count=0,
            ),
        ],
        overall_confidences=[],
        sampled_documents=5,
    )
    out = compute_classifier_uncertainty(raw, tenant_config)
    assert out.uncertain_pairs[0].confusion_rate == 0.0


# ---------------------------------------------------------------------------
# 3.8 — IngestionPipelineMetrics
# ---------------------------------------------------------------------------


def test_compute_pipeline_metrics_summarizes_chunk_counts(tenant_config):
    raw = RawIngestionPipelineMetricsEvent(
        tenant_anon_id=SAFE_ANON_ID,
        chunker_strategy="semantic",
        embedding_provider_family="openai",
        embedding_dim=1024,
        docs_processed=450,
        chunks_per_doc=[3, 5, 8, 10, 15, 22, 30, 45, 80],
        classification_failures=15,
        ontology_assignment_failures=22,
    )
    out = compute_ingestion_pipeline_metrics(raw, tenant_config)
    assert out.docs_processed_bucket == "101-1000"
    assert out.chunks_per_doc_p50 >= 0
    assert out.chunks_per_doc_p95 >= out.chunks_per_doc_p50
    assert out.classification_failure_rate == pytest.approx(15 / 450)
    assert out.ontology_assignment_failure_rate == pytest.approx(22 / 450)


def test_compute_pipeline_metrics_zero_docs_safe(tenant_config):
    raw = RawIngestionPipelineMetricsEvent(
        tenant_anon_id=SAFE_ANON_ID,
        chunker_strategy="fixed_token",
        embedding_provider_family="bge",
        embedding_dim=1024,
        docs_processed=0,
        chunks_per_doc=[],
        classification_failures=0,
        ontology_assignment_failures=0,
    )
    out = compute_ingestion_pipeline_metrics(raw, tenant_config)
    # docs_processed=0 is clamped to 1 just for bucket-min compliance
    assert out.docs_processed_bucket == "1-10"
    assert out.chunks_per_doc_p50 == 0
    assert out.chunks_per_doc_p95 == 0
    assert out.classification_failure_rate == 0.0

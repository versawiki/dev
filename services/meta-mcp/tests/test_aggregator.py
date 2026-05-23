"""SignatureAggregator: grouping, distinct-tenant counting, threshold boundaries."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from versawiki_meta_mcp.schema.observation import (
    DomainObservationEnvelope,
    NamingConvention,
    OntologyShape,
    RelationshipEdge,
    RelationshipSchema,
)
from versawiki_meta_mcp.skills.aggregator import SignatureAggregator
from versawiki_meta_mcp.skills.thresholds import (
    SkillWriteThreshold,
    SkillWriteThresholds,
)
from versawiki_meta_mcp.store.file_store import FileMetaStore


def _run(awaitable):
    return asyncio.run(awaitable)


TENANTS = [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
]

_BASE = "abcdefab-cdef-4abc-9abc-abcdefab"


def _make_naming_env(tenant: str, idx: int) -> DomainObservationEnvelope:
    return DomainObservationEnvelope(
        event_id=f"{_BASE}{idx:04x}",
        schema_version="1.0.0",
        observed_at_utc=datetime.now(timezone.utc),
        tenant_anon_id=tenant,
        opt_out_flag=False,
        domain_signature_id=None,
        payload=NamingConvention(
            applies_to="drawing_number",
            template="<phase>-<discipline>-<sequence>",
            token_vocabulary=["phase", "discipline", "sequence"],
            sample_count_bucket="51-200",
            adherence_rate=0.93,
        ),
    )


def _make_ontology_env(tenant: str, idx: int) -> DomainObservationEnvelope:
    return DomainObservationEnvelope(
        event_id=f"{_BASE}{idx:04x}",
        schema_version="1.0.0",
        observed_at_utc=datetime.now(timezone.utc),
        tenant_anon_id=tenant,
        opt_out_flag=False,
        domain_signature_id=None,
        payload=OntologyShape(
            depth=4,
            node_count_bucket="51-200",
            branching_factor_p50=0.5,
            branching_factor_p95=0.85,
            leaf_to_internal_ratio=0.7,
            kind_distribution={"category": 5, "entity": 10},
        ),
    )


def _make_rel_env(tenant: str, idx: int, low_conf: bool = False) -> DomainObservationEnvelope:
    return DomainObservationEnvelope(
        event_id=f"{_BASE}{idx:04x}",
        schema_version="1.0.0",
        observed_at_utc=datetime.now(timezone.utc),
        tenant_anon_id=tenant,
        opt_out_flag=False,
        domain_signature_id=None,
        payload=RelationshipSchema(
            edges=[
                RelationshipEdge(
                    source_type="drawing",
                    target_type="specification",
                    relation="references",
                    detection_method="label_pattern",
                    edge_count_bucket="11-100",
                    confidence_p50=0.4 if low_conf else 0.9,
                ),
            ],
        ),
    )


def test_groups_by_domain_and_kind(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    # 2 naming + 2 ontology, single tenant.
    for i in range(2):
        _run(store.write_observation(_make_naming_env(TENANTS[0], i)))
    for i in range(2):
        _run(store.write_observation(_make_ontology_env(TENANTS[0], 10 + i)))

    agg = SignatureAggregator(meta_store=store)
    groups = _run(agg.compute_all_groups())

    by_kind = {g.kind: g for g in groups}
    assert "naming-convention" in by_kind
    assert "ontology-shape" in by_kind
    assert by_kind["naming-convention"].observation_count == 2
    assert by_kind["ontology-shape"].observation_count == 2


def test_distinct_tenants_counted_correctly(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    # 3 tenants, 5 naming events each.
    for t_idx, t in enumerate(TENANTS[:3]):
        for i in range(5):
            _run(store.write_observation(_make_naming_env(t, t_idx * 100 + i)))

    agg = SignatureAggregator(meta_store=store)
    groups = _run(agg.compute_all_groups())
    [naming] = [g for g in groups if g.kind == "naming-convention"]
    assert naming.distinct_tenants == 3
    assert naming.observation_count == 15


def test_threshold_boundary_min_distinct_tenants(tmp_path: Path) -> None:
    """Group with 2 tenants does NOT cross; 3 tenants DOES."""

    store = FileMetaStore(tmp_path / "meta")
    thresholds = SkillWriteThresholds(
        default=SkillWriteThreshold(
            min_distinct_tenants=3, min_observations=3, confidence_floor=0.0
        )
    )

    # 2 tenants, 5 events each. Below tenant threshold.
    for t_idx, t in enumerate(TENANTS[:2]):
        for i in range(5):
            _run(store.write_observation(_make_naming_env(t, t_idx * 100 + i)))

    agg = SignatureAggregator(meta_store=store, thresholds=thresholds)
    assert _run(agg.compute_threshold_crossing_groups()) == []

    # Add a 3rd tenant. Now crosses.
    for i in range(5):
        _run(store.write_observation(_make_naming_env(TENANTS[2], 200 + i)))
    crossing = _run(agg.compute_threshold_crossing_groups())
    assert len(crossing) == 1
    assert crossing[0].distinct_tenants == 3


def test_threshold_boundary_min_observations(tmp_path: Path) -> None:
    """Below min_observations -> no crossing; at-or-above -> crossing."""

    store = FileMetaStore(tmp_path / "meta")
    thresholds = SkillWriteThresholds(
        default=SkillWriteThreshold(
            min_distinct_tenants=2, min_observations=10, confidence_floor=0.0
        )
    )

    # 3 tenants, 3 events each = 9 < 10. Below.
    for t_idx, t in enumerate(TENANTS[:3]):
        for i in range(3):
            _run(store.write_observation(_make_naming_env(t, t_idx * 100 + i)))
    agg = SignatureAggregator(meta_store=store, thresholds=thresholds)
    assert _run(agg.compute_threshold_crossing_groups()) == []

    # One more event -> 10 == 10. Crosses.
    _run(store.write_observation(_make_naming_env(TENANTS[0], 999)))
    crossing = _run(agg.compute_threshold_crossing_groups())
    assert len(crossing) == 1
    assert crossing[0].observation_count == 10


def test_threshold_boundary_confidence_floor(tmp_path: Path) -> None:
    """Mean confidence below the floor -> no crossing; at-or-above -> crossing.

    We use RelationshipSchema with confidence_p50=0.4 (low) vs 0.9 (high)
    to exercise the floor.
    """

    store = FileMetaStore(tmp_path / "meta")
    thresholds = SkillWriteThresholds(
        default=SkillWriteThreshold(
            min_distinct_tenants=2,
            min_observations=3,
            confidence_floor=0.7,
        )
    )

    # 3 tenants, 4 events each, ALL low-confidence (0.4).
    for t_idx, t in enumerate(TENANTS[:3]):
        for i in range(4):
            _run(store.write_observation(_make_rel_env(t, t_idx * 100 + i, low_conf=True)))
    agg = SignatureAggregator(meta_store=store, thresholds=thresholds)
    assert _run(agg.compute_threshold_crossing_groups()) == []

    # Now swap to high confidence — fresh store.
    store2 = FileMetaStore(tmp_path / "meta2")
    for t_idx, t in enumerate(TENANTS[:3]):
        for i in range(4):
            _run(store2.write_observation(_make_rel_env(t, t_idx * 100 + i, low_conf=False)))
    agg2 = SignatureAggregator(meta_store=store2, thresholds=thresholds)
    crossing = _run(agg2.compute_threshold_crossing_groups())
    assert len(crossing) == 1
    assert crossing[0].mean_confidence >= 0.7


def test_shape_examples_are_content_free(tmp_path: Path) -> None:
    """The shape_examples list should be Literal-vocab strings only."""

    store = FileMetaStore(tmp_path / "meta")
    for i in range(3):
        _run(store.write_observation(_make_naming_env(TENANTS[i], i)))

    agg = SignatureAggregator(meta_store=store)
    groups = _run(agg.compute_all_groups())
    [naming] = [g for g in groups if g.kind == "naming-convention"]
    assert naming.shape_examples
    for s in naming.shape_examples:
        # Fingerprints look like "naming::<phase>-<discipline>-<sequence>".
        assert s.startswith("naming::")
        # No raw counts, no email markers, etc.
        assert "@" not in s


def test_per_domain_threshold_override(tmp_path: Path) -> None:
    """A per-domain override should beat the default."""

    store = FileMetaStore(tmp_path / "meta")
    for t_idx, t in enumerate(TENANTS[:3]):
        for i in range(5):
            _run(store.write_observation(_make_naming_env(t, t_idx * 100 + i)))

    # Strict default but generous AEC override -> AEC group crosses.
    thresholds = SkillWriteThresholds(
        default=SkillWriteThreshold(
            min_distinct_tenants=100, min_observations=100, confidence_floor=0.0
        ),
        per_domain={
            "AEC": SkillWriteThreshold(
                min_distinct_tenants=2, min_observations=3, confidence_floor=0.0
            )
        },
    )
    agg = SignatureAggregator(meta_store=store, thresholds=thresholds)
    crossing = _run(agg.compute_threshold_crossing_groups())
    assert len(crossing) == 1
    assert crossing[0].domain == "AEC"


def test_empty_store_returns_no_groups(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    agg = SignatureAggregator(meta_store=store)
    assert _run(agg.compute_all_groups()) == []
    assert _run(agg.compute_threshold_crossing_groups()) == []

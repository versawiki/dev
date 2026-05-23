"""Round-trip every payload variant through the envelope; check that
`extra="forbid"` and the discriminated union behave as the spec says.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from versawiki_meta_mcp.schema.observation import (
    ClassifierUncertainty,
    DocumentTypeDistribution,
    DomainObservationEnvelope,
    IngestionPipelineMetrics,
    NamingConvention,
    OntologyShape,
    ProcedurePattern,
    QueryPatternShape,
    RelationshipSchema,
)


_KIND_TO_MODEL = {
    "ontology_shape": OntologyShape,
    "naming_convention": NamingConvention,
    "document_type_distribution": DocumentTypeDistribution,
    "relationship_schema": RelationshipSchema,
    "procedure_pattern": ProcedurePattern,
    "query_pattern_shape": QueryPatternShape,
    "classifier_uncertainty": ClassifierUncertainty,
    "ingestion_pipeline_metrics": IngestionPipelineMetrics,
}


def test_envelope_round_trip_all_eight_variants(
    envelope_of, all_principle_payloads
):
    """Each of the 8 payload variants round-trips through the envelope
    and the discriminated union routes to the correct concrete model.
    """

    seen_kinds: set[str] = set()
    for payload in all_principle_payloads:
        env_dict = envelope_of(payload)
        env = DomainObservationEnvelope.model_validate(env_dict)

        # Round trip through model_dump.
        dumped = env.model_dump(mode="json")
        re_env = DomainObservationEnvelope.model_validate(dumped)
        assert re_env == env

        # Discriminator routed correctly.
        kind = payload["kind"]
        expected_cls = _KIND_TO_MODEL[kind]
        assert isinstance(env.payload, expected_cls), (
            f"kind={kind} routed to {type(env.payload).__name__}, "
            f"expected {expected_cls.__name__}"
        )
        seen_kinds.add(kind)

    # We tested all 8.
    assert seen_kinds == set(_KIND_TO_MODEL.keys())


def test_envelope_extra_forbid_rejects_unknown_top_level_field(
    envelope_of, payload_ontology_shape
):
    bad = envelope_of(payload_ontology_shape)
    bad["sneaky_field"] = "leak"
    with pytest.raises(ValidationError):
        DomainObservationEnvelope.model_validate(bad)


def test_payload_extra_forbid_rejects_unknown_nested_field(
    envelope_of, payload_ontology_shape
):
    tainted = dict(payload_ontology_shape)
    tainted["customer_name"] = "Acme Corp"
    bad = envelope_of(tainted)
    with pytest.raises(ValidationError):
        DomainObservationEnvelope.model_validate(bad)


def test_discriminator_required(envelope_of):
    """A payload without `kind` must fail validation, not silently
    pick a default variant."""

    bad = envelope_of({"depth": 1})  # no `kind`
    with pytest.raises(ValidationError):
        DomainObservationEnvelope.model_validate(bad)


def test_discriminator_unknown_kind_rejected(envelope_of):
    bad = envelope_of({"kind": "totally_made_up", "x": 1})
    with pytest.raises(ValidationError):
        DomainObservationEnvelope.model_validate(bad)

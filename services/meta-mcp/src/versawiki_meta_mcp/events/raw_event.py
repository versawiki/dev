"""Tenant-private raw-ingestion event types.

These models are what the ingestion service emits *before* signature
computation. They contain:

  * raw counts (not bucketed)
  * tenant-side type labels and classifier confidences per-document
  * file paths, query strings, document IDs
  * other CONTENT-class fields

By construction they must NEVER be serialized to a `DomainObservationEnvelope`
or crossed to the meta store. The `SignatureCollector` is the one place that
reads them; everything downstream consumes the principle-only envelope.

A `RawIngestionEvent` is a discriminated union over the 8 payload variants
defined in spec §3 (mirrored 1:1 by `schema.observation`). Each variant
carries exactly the fields the corresponding `compute_<variant>()` function
needs to derive bucketed / templated / vocabulary-mapped principle output.

Design rule: every numeric field on a raw event must be the *raw* number
the ingestion service measured. The collector is the only thing that
converts raw -> bucket. If a raw event already carries a bucket string,
something upstream has done part of the collector's job — that's a smell
worth investigating in code review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Common base — every raw event carries identity & correlation locally.
# ---------------------------------------------------------------------------


class _RawEventBase(BaseModel):
    """Common fields. Note: `extra="forbid"` defends against accidental
    fields creeping in upstream and silently riding to the collector.
    """

    model_config = ConfigDict(extra="forbid", validate_default=True)

    # Local correlation: the tenant ingestion service may match raw events
    # back to ingestion runs by these. Never crosses the boundary.
    raw_event_id: UUID = Field(default_factory=uuid4)
    observed_at_utc: AwareDatetime = Field(default_factory=lambda: datetime.utcnow().astimezone())

    # Tenant *anonymous* id. Same value the collector will copy into the
    # outbound envelope — this is the only field that does cross. See spec §2.1.
    tenant_anon_id: str = Field(min_length=22, max_length=64)


# ---------------------------------------------------------------------------
# 3.1 — OntologyShape inputs
# ---------------------------------------------------------------------------


class RawOntologyShapeEvent(_RawEventBase):
    """Raw inputs for `compute_ontology_shape`.

    `node_count`, `node_labels`, `branching_factors`, `kind_distribution`
    are the tenant-side observations. The collector buckets / aggregates
    these into principle form. `node_labels` is here only to make the raw
    event self-describing for tenant-local debugging; the collector never
    reads it.
    """

    kind: Literal["ontology_shape"] = "ontology_shape"

    depth: int = Field(ge=0, le=64)
    node_count: int = Field(ge=0)
    branching_factors: list[float] = Field(default_factory=list)
    # Raw per-node kind tally (tenant-side label tally, summed by kind).
    kind_distribution: dict[Literal["category", "entity", "topic"], int] = Field(
        default_factory=dict
    )
    # CONTENT — for tenant-local debugging only. Collector ignores.
    node_labels: list[str] = Field(default_factory=list)
    # Optional: how many nodes were seeded vs induced.
    induced_node_count: int | None = Field(default=None, ge=0)
    seed_node_count: int | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# 3.2 — NamingConvention inputs
# ---------------------------------------------------------------------------


class RawNamingConventionEvent(_RawEventBase):
    """Raw inputs for `compute_naming_convention`.

    The collector uses `tenant_role_token_map` from the tenant config to
    rewrite tenant-side token names ("DD", "ELE") into the principle
    vocabulary ("phase", "discipline"). The template here is allowed to
    contain tenant-side tokens because it never leaves the process; the
    collector rewrites it.
    """

    kind: Literal["naming_convention"] = "naming_convention"

    applies_to: Literal[
        "document_id",
        "drawing_number",
        "spec_section",
        "rfi_id",
        "submittal_id",
        "other_identifier",
    ]
    # Tenant-side template — may contain free tokens like "<DD>-<ELE>-<NNN>".
    # The collector maps each tenant token to the principle vocabulary and
    # rebuilds the template before emit.
    raw_template: str = Field(min_length=1, max_length=512)
    # Counts: how many identifiers matched the template, and how many were
    # sampled in total. Ratio = match/sample.
    matched_count: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    # CONTENT — example strings used to derive the template. NEVER crosses.
    example_identifiers: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.3 — DocumentTypeDistribution inputs
# ---------------------------------------------------------------------------


class RawDocumentTypeDistributionEvent(_RawEventBase):
    """Raw inputs for `compute_document_type_distribution`.

    `tenant_type_counts` is the tenant's own type taxonomy. The collector
    maps each tenant-side type to its `GenericDocType` via the tenant config
    and then buckets the count.
    """

    kind: Literal["document_type_distribution"] = "document_type_distribution"

    # Raw per-tenant-type counts. Tenant-side labels — must be mapped.
    tenant_type_counts: dict[str, int] = Field(default_factory=dict)
    total_documents: int = Field(ge=0)
    # List of all observed classifier confidences (one per document, or a
    # sample). Collector computes p10 and p50.
    classifier_confidences: list[float] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.4 — RelationshipSchema inputs
# ---------------------------------------------------------------------------


class RawRelationshipEdgeObservation(BaseModel):
    """One edge observation. Source/target are tenant-side type labels."""

    model_config = ConfigDict(extra="forbid")

    source_tenant_type: str
    target_tenant_type: str
    relation: Literal[
        "references",
        "supersedes",
        "responds_to",
        "approves",
        "schedules",
        "summarizes",
        "computes_for",
        "annotates",
    ]
    detection_method: Literal[
        "label_pattern",
        "embedding_proximity",
        "explicit_field",
        "llm_extraction",
    ]
    edge_count: int = Field(ge=0)
    confidences: list[float] = Field(default_factory=list)


class RawRelationshipSchemaEvent(_RawEventBase):
    """Raw inputs for `compute_relationship_schema`."""

    kind: Literal["relationship_schema"] = "relationship_schema"

    edges: list[RawRelationshipEdgeObservation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.5 — ProcedurePattern inputs
# ---------------------------------------------------------------------------


class RawProcedurePatternEvent(_RawEventBase):
    """Raw inputs for `compute_procedure_pattern`."""

    kind: Literal["procedure_pattern"] = "procedure_pattern"

    # Tenant-side type label — collector maps to ProcedureDocType.
    applies_to_tenant_type: str
    # Tenant-side state names — collector maps via tenant config to the
    # controlled lifecycle vocabulary.
    tenant_states: list[str] = Field(default_factory=list)
    transitions_observed: int = Field(ge=0)
    # Per-document lifecycle lengths.
    lifecycle_state_counts: list[int] = Field(default_factory=list)
    detection_method: Literal[
        "revision_metadata",
        "filename_token",
        "llm_extraction",
        "explicit_field",
    ]


# ---------------------------------------------------------------------------
# 3.6 — QueryPatternShape inputs
# ---------------------------------------------------------------------------


class RawQueryPatternShapeEvent(_RawEventBase):
    """Raw inputs for `compute_query_pattern_shape`.

    `raw_query_strings` and `raw_template` are CONTENT; they MUST NOT cross.
    The collector canonicalizes the template against the tenant config's
    query-token map.
    """

    kind: Literal["query_pattern_shape"] = "query_pattern_shape"

    # Tenant-side template, possibly with tenant-side tokens.
    raw_template: str = Field(min_length=1, max_length=512)
    occurrence_count: int = Field(ge=0)
    caller_kind: Literal["human", "mcp", "mixed"]
    # CONTENT — example query strings the template was induced from.
    raw_query_strings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.7 — ClassifierUncertainty inputs
# ---------------------------------------------------------------------------


class RawUncertainPairObservation(BaseModel):
    """One confusion pair, tenant-side."""

    model_config = ConfigDict(extra="forbid")

    tenant_type_a: str
    tenant_type_b: str
    confused_count: int = Field(ge=0)
    total_count: int = Field(ge=0)


class RawClassifierUncertaintyEvent(_RawEventBase):
    """Raw inputs for `compute_classifier_uncertainty`."""

    kind: Literal["classifier_uncertainty"] = "classifier_uncertainty"

    uncertain_pairs: list[RawUncertainPairObservation] = Field(default_factory=list)
    overall_confidences: list[float] = Field(default_factory=list)
    sampled_documents: int = Field(ge=0)


# ---------------------------------------------------------------------------
# 3.8 — IngestionPipelineMetrics inputs
# ---------------------------------------------------------------------------


class RawIngestionPipelineMetricsEvent(_RawEventBase):
    """Raw inputs for `compute_ingestion_pipeline_metrics`."""

    kind: Literal["ingestion_pipeline_metrics"] = "ingestion_pipeline_metrics"

    chunker_strategy: Literal["fixed_token", "semantic", "structural", "hybrid"]
    embedding_provider_family: Literal["openai", "bge", "voyage", "nomic", "other"]
    embedding_dim: Literal[1024]
    docs_processed: int = Field(ge=0)
    chunks_per_doc: list[int] = Field(default_factory=list)
    classification_failures: int = Field(ge=0)
    ontology_assignment_failures: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

RawIngestionEvent = Annotated[
    Union[
        RawOntologyShapeEvent,
        RawNamingConventionEvent,
        RawDocumentTypeDistributionEvent,
        RawRelationshipSchemaEvent,
        RawProcedurePatternEvent,
        RawQueryPatternShapeEvent,
        RawClassifierUncertaintyEvent,
        RawIngestionPipelineMetricsEvent,
    ],
    Field(discriminator="kind"),
]

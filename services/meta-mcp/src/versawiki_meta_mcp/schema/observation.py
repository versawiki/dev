"""DomainObservation wire format (v1).

Source of truth: `docs/architecture/domain-observation-v1.md`. This module
mirrors §2 (envelope) and §3 (8 payload variants) exactly. The schema IS the
contract; any change here is a v2 conversation per §7.

Every Pydantic model in this file pins `extra="forbid"` and `frozen=True`.
Together with the §4 forbidden-field list and the static checker pipeline
(`versawiki_meta_mcp.checkers.pipeline`) this is the operational enforcement
of versawiki's privacy promise.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Controlled vocabularies (baked into the schema per DECISIONS 2026-05-22 #2).
# Adding members is a MINOR bump; removing or narrowing is MAJOR. The static
# checkers' NER whitelist is built off of these literals at runtime so adding
# a member here makes that literal an allowed string everywhere.
# ---------------------------------------------------------------------------

GenericDocType = Literal[
    "drawing",
    "specification",
    "rfi",
    "submittal",
    "meeting_minutes",
    "report",
    "calculation",
    "contract",
    "correspondence",
    "schedule",
    "image",
    "spreadsheet",
    "presentation",
    "other",
]

# RelationshipEdge / ProcedurePattern / ClassifierUncertainty all use a
# slightly narrower variant: no "image"/"spreadsheet"/"presentation" because
# those aren't endpoints of structural relationships. Per spec §3.4/§3.5/§3.7.
RelationDocType = Literal[
    "drawing",
    "specification",
    "rfi",
    "submittal",
    "meeting_minutes",
    "report",
    "calculation",
    "contract",
    "correspondence",
    "schedule",
    "other",
]

ProcedureDocType = Literal[
    "drawing",
    "specification",
    "rfi",
    "submittal",
    "report",
    "calculation",
    "other",
]

CountBucket10_1000plus = Literal["1-10", "11-50", "51-200", "201-1000", "1000+"]
DocTotalBucket = Literal[
    "1-10", "11-50", "51-200", "201-1000", "1001-10000", "10000+"
]
PerTypeCountBucket = Literal["0", "1-10", "11-50", "51-200", "201-1000", "1000+"]
NamingSampleBucket = Literal["3-10", "11-50", "51-200", "200+"]
EdgeCountBucket = Literal["1-10", "11-100", "101-1000", "1000+"]
TransitionsBucket = Literal["1-10", "11-100", "101-1000", "1000+"]
SampledDocsBucket = Literal["1-10", "11-100", "101-1000", "1000+"]
DocsProcessedBucket = Literal["1-10", "11-100", "101-1000", "1000+"]
QueryOccurrenceBucket = Literal["3-10", "11-50", "51-200", "200+"]


# Single source of truth for "any string literal that's allowed to cross the
# boundary." Used by the PII / NER checker to whitelist members of controlled
# vocabularies. Adding to this set is privacy-relevant — any new "free string"
# entry would defeat the §4 rule of thumb.
def _literal_members(*literal_types: object) -> frozenset[str]:
    out: set[str] = set()
    for lit in literal_types:
        args = getattr(lit, "__args__", ())
        for a in args:
            if isinstance(a, str):
                out.add(a)
    return frozenset(out)


ALLOWED_LITERAL_STRINGS: frozenset[str] = _literal_members(
    GenericDocType,
    RelationDocType,
    ProcedureDocType,
    CountBucket10_1000plus,
    DocTotalBucket,
    PerTypeCountBucket,
    NamingSampleBucket,
    EdgeCountBucket,
    TransitionsBucket,
    SampledDocsBucket,
    DocsProcessedBucket,
    QueryOccurrenceBucket,
    Literal["category", "entity", "topic"],
    Literal[
        "document_id",
        "drawing_number",
        "spec_section",
        "rfi_id",
        "submittal_id",
        "other_identifier",
    ],
    Literal[
        "phase",
        "discipline",
        "sequence",
        "revision",
        "date_yyyymmdd",
        "date_yyyymm",
        "type_code",
        "subtype_code",
        "version",
        "lot",
        "drawing_set",
        "rfi_round",
        "other",
    ],
    Literal[
        "references",
        "supersedes",
        "responds_to",
        "approves",
        "schedules",
        "summarizes",
        "computes_for",
        "annotates",
    ],
    Literal[
        "label_pattern",
        "embedding_proximity",
        "explicit_field",
        "llm_extraction",
    ],
    Literal[
        "draft",
        "in_review",
        "reviewed",
        "issued_for_information",
        "issued_for_bid",
        "issued_for_construction",
        "as_built",
        "open",
        "responded",
        "closed",
        "approved",
        "rejected",
        "superseded",
        "void",
        "record",
        "other",
    ],
    Literal[
        "revision_metadata",
        "filename_token",
        "llm_extraction",
        "explicit_field",
    ],
    Literal["type", "identifier_kind", "topic", "phase", "discipline",
            "date_range", "status", "other"],
    Literal["human", "mcp", "mixed"],
    Literal["fixed_token", "semantic", "structural", "hybrid"],
    Literal["openai", "bge", "voyage", "nomic", "other"],
    # ontology_shape / naming_convention / ... discriminator values:
    Literal[
        "ontology_shape",
        "naming_convention",
        "document_type_distribution",
        "relationship_schema",
        "procedure_pattern",
        "query_pattern_shape",
        "classifier_uncertainty",
        "ingestion_pipeline_metrics",
    ],
    Literal["1.0.0"],
)


# ---------------------------------------------------------------------------
# Payload variants (§3). All extra="forbid", all frozen.
# ---------------------------------------------------------------------------


class OntologyShape(BaseModel):
    """§3.1 — coarse shape of the tenant's induced ontology."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["ontology_shape"] = "ontology_shape"

    depth: int = Field(ge=0, le=64)
    node_count_bucket: CountBucket10_1000plus
    branching_factor_p50: float = Field(ge=0.0)
    branching_factor_p95: float = Field(ge=0.0)
    leaf_to_internal_ratio: float = Field(ge=0.0)
    kind_distribution: dict[Literal["category", "entity", "topic"], int]
    induced_vs_seed_ratio: float | None = Field(default=None, ge=0.0, le=1.0)


class NamingConvention(BaseModel):
    """§3.2 — naming template expressed as role tokens, not example strings."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["naming_convention"] = "naming_convention"

    applies_to: Literal[
        "document_id",
        "drawing_number",
        "spec_section",
        "rfi_id",
        "submittal_id",
        "other_identifier",
    ]
    template: str = Field(pattern=r"^[<>a-z\-_]+$", min_length=1, max_length=128)
    token_vocabulary: list[
        Literal[
            "phase",
            "discipline",
            "sequence",
            "revision",
            "date_yyyymmdd",
            "date_yyyymm",
            "type_code",
            "subtype_code",
            "version",
            "lot",
            "drawing_set",
            "rfi_round",
            "other",
        ]
    ]
    sample_count_bucket: NamingSampleBucket
    adherence_rate: float = Field(ge=0.0, le=1.0)


class DocumentTypeDistribution(BaseModel):
    """§3.3 — distribution of *generic* document types."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["document_type_distribution"] = "document_type_distribution"

    generic_type_counts: dict[GenericDocType, PerTypeCountBucket]
    total_documents_bucket: DocTotalBucket
    classifier_confidence_p50: float = Field(ge=0.0, le=1.0)
    classifier_confidence_p10: float = Field(ge=0.0, le=1.0)


class RelationshipEdge(BaseModel):
    """§3.4 — an edge in the relationship schema."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    source_type: RelationDocType
    target_type: RelationDocType
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
    edge_count_bucket: EdgeCountBucket
    confidence_p50: float = Field(ge=0.0, le=1.0)


class RelationshipSchema(BaseModel):
    """§3.4 — collection of relationship edges."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["relationship_schema"] = "relationship_schema"

    edges: list[RelationshipEdge] = Field(min_length=0, max_length=256)


class ProcedurePattern(BaseModel):
    """§3.5 — lifecycle states observed across documents of a generic type."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["procedure_pattern"] = "procedure_pattern"

    applies_to_type: ProcedureDocType
    states: list[
        Literal[
            "draft",
            "in_review",
            "reviewed",
            "issued_for_information",
            "issued_for_bid",
            "issued_for_construction",
            "as_built",
            "open",
            "responded",
            "closed",
            "approved",
            "rejected",
            "superseded",
            "void",
            "record",
            "other",
        ]
    ]
    transitions_observed_bucket: TransitionsBucket
    median_lifecycle_states: int = Field(ge=0, le=32)
    detection_method: Literal[
        "revision_metadata",
        "filename_token",
        "llm_extraction",
        "explicit_field",
    ]


class QueryPatternShape(BaseModel):
    """§3.6 — canonicalized shape of recurring queries (no entities)."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["query_pattern_shape"] = "query_pattern_shape"

    shape_template: str = Field(
        pattern=r"^[<>a-z\-_ ]+$", min_length=1, max_length=128
    )
    token_vocabulary: list[
        Literal[
            "type",
            "identifier_kind",
            "topic",
            "phase",
            "discipline",
            "date_range",
            "status",
            "other",
        ]
    ]
    occurrence_count_bucket: QueryOccurrenceBucket
    caller_kind: Literal["human", "mcp", "mixed"]


class UncertainPair(BaseModel):
    """§3.7 — a (type_a, type_b) confusion pair."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    type_a: RelationDocType
    type_b: RelationDocType
    confusion_rate: float = Field(ge=0.0, le=1.0)


class ClassifierUncertainty(BaseModel):
    """§3.7 — where the classifier is hesitant, by generic type only."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["classifier_uncertainty"] = "classifier_uncertainty"

    uncertain_pairs: list[UncertainPair] = Field(min_length=0, max_length=256)
    overall_confidence_p10: float = Field(ge=0.0, le=1.0)
    sampled_documents_bucket: SampledDocsBucket


class IngestionPipelineMetrics(BaseModel):
    """§3.8 — pipeline shape, useful for picking strategies per domain."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: Literal["ingestion_pipeline_metrics"] = "ingestion_pipeline_metrics"

    chunker_strategy: Literal[
        "fixed_token", "semantic", "structural", "hybrid"
    ]
    embedding_provider_family: Literal[
        "openai", "bge", "voyage", "nomic", "other"
    ]
    embedding_dim: Literal[1024]
    docs_processed_bucket: DocsProcessedBucket
    chunks_per_doc_p50: int = Field(ge=0, le=10_000)
    chunks_per_doc_p95: int = Field(ge=0, le=10_000)
    classification_failure_rate: float = Field(ge=0.0, le=1.0)
    ontology_assignment_failure_rate: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Discriminated union of all payload variants. The `kind` field routes.
# ---------------------------------------------------------------------------

DomainObservationPayload = Annotated[
    Union[
        OntologyShape,
        NamingConvention,
        DocumentTypeDistribution,
        RelationshipSchema,
        ProcedurePattern,
        QueryPatternShape,
        ClassifierUncertainty,
        IngestionPipelineMetrics,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Envelope (§2). Every event that crosses the boundary is one of these.
# ---------------------------------------------------------------------------


class DomainObservationEnvelope(BaseModel):
    """The one and only wire-format envelope for the tenant -> meta-MCP edge.

    Per `docs/architecture/domain-observation-v1.md` §2: every field on this
    envelope or its payload must be either PRINCIPLE (generalizable shape) or
    METADATA (system-level). CONTENT (customer-specific names, figures, file
    paths, quotes) is never present.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    # ---- Identity & versioning (METADATA) ----
    event_id: UUID
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    observed_at_utc: AwareDatetime

    # ---- Anonymous tenant correlation (METADATA) ----
    # See §2.1: UUIDv4 issued at tenant provisioning. Mapping back to a
    # tenant_id lives only in the tenant's own schema.
    tenant_anon_id: str = Field(min_length=22, max_length=64)
    opt_out_flag: bool = False

    # ---- Domain grouping (METADATA) ----
    domain_signature_id: UUID | None = None

    # ---- Payload (discriminated union of PRINCIPLE-only payloads) ----
    payload: DomainObservationPayload

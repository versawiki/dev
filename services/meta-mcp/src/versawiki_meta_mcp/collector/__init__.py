"""Signature collector — tenant->meta-MCP boundary, operational side.

`SignatureCollector` is the only call path from a tenant-private
`RawIngestionEvent` to a meta-store-written `DomainObservationEnvelope`.
Every codepath that constructs a payload from a raw event goes through
the checker pipeline first. If you find an alternate path that bypasses
the checker, that is a P0 — document it in `notes/mcp-builder.md` and
re-route through this module.
"""

from .collector import (
    CollectorOutcome,
    CollectorResult,
    SignatureCollector,
)
from .signatures import (
    compute_classifier_uncertainty,
    compute_document_type_distribution,
    compute_ingestion_pipeline_metrics,
    compute_naming_convention,
    compute_ontology_shape,
    compute_procedure_pattern,
    compute_query_pattern_shape,
    compute_relationship_schema,
)
from .tenant_config import (
    DEFAULT_BUCKETS,
    BucketBoundaries,
    TenantSignatureConfig,
)

__all__ = [
    "SignatureCollector",
    "CollectorOutcome",
    "CollectorResult",
    "TenantSignatureConfig",
    "BucketBoundaries",
    "DEFAULT_BUCKETS",
    "compute_ontology_shape",
    "compute_naming_convention",
    "compute_document_type_distribution",
    "compute_relationship_schema",
    "compute_procedure_pattern",
    "compute_query_pattern_shape",
    "compute_classifier_uncertainty",
    "compute_ingestion_pipeline_metrics",
]

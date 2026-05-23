"""Raw ingestion-event types and subscriber protocol.

`RawIngestionEvent` is the *tenant-private* shape: it carries file paths,
classifier outputs, raw counts, query strings. It MUST NOT leave the tenant
process. The signature collector (`collector/`) consumes raw events and
emits `DomainObservationEnvelope`s — that envelope is the only thing allowed
across the meta boundary.

If you find yourself importing `RawIngestionEvent` outside the tenant
process boundary, stop — that is a privacy violation. Add the import path
to `notes/mcp-builder.md` and re-design.
"""

from .raw_event import (
    RawClassifierUncertaintyEvent,
    RawDocumentTypeDistributionEvent,
    RawIngestionEvent,
    RawIngestionPipelineMetricsEvent,
    RawNamingConventionEvent,
    RawOntologyShapeEvent,
    RawProcedurePatternEvent,
    RawQueryPatternShapeEvent,
    RawRelationshipEdgeObservation,
    RawRelationshipSchemaEvent,
    RawUncertainPairObservation,
)
from .subscriber import EventSubscriber, InProcessSubscriber

__all__ = [
    "EventSubscriber",
    "InProcessSubscriber",
    "RawIngestionEvent",
    "RawOntologyShapeEvent",
    "RawNamingConventionEvent",
    "RawDocumentTypeDistributionEvent",
    "RawRelationshipSchemaEvent",
    "RawRelationshipEdgeObservation",
    "RawProcedurePatternEvent",
    "RawQueryPatternShapeEvent",
    "RawClassifierUncertaintyEvent",
    "RawUncertainPairObservation",
    "RawIngestionPipelineMetricsEvent",
]

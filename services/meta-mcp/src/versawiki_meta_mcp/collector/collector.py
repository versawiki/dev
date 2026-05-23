"""`SignatureCollector` — the operational tenant->meta boundary.

State machine for each event:

    raw event in
      |
      v
   [opt-out gate]  -- opt_out=True --> audit log (reason OPT_OUT) + drop
      |
      v
   [signature compute]  -- exception --> audit log (reason SCHEMA_VALIDATION_FAILED)
      |                                  + drop (no envelope ever built)
      v
   [envelope build]  -- ValidationError --> audit log (reason SCHEMA_VALIDATION_FAILED)
      |                                     + drop
      v
   [checker pipeline]  -- any failure --> audit log (reason from chain) + drop
      |
      v
   [meta store write]  -- on success only

Per ticket: every codepath that constructs a payload from a raw event MUST go
through the checker pipeline. There is exactly one such path (the `_process`
method below). If you find another, that is a P0.

We also enforce the privacy promise on the audit-log entry: a rejection only
records (payload_hash, reason_code, stage). The raw event itself is never
passed to the audit log.

Logging discipline: this module logs at INFO/WARN only the `payload_hash`
and the reason — never the event body. If a debug message needs more
context, add it to the per-stage `CheckResult.details`, which is already
content-free.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import AsyncIterator, Optional

from pydantic import ValidationError

from ..audit.tenant_audit_log import TenantAuditLog
from ..checkers.pipeline import CheckerPipeline, _compute_payload_hash
from ..checkers.results import ReasonCode, Stage
from ..events.raw_event import (
    RawClassifierUncertaintyEvent,
    RawDocumentTypeDistributionEvent,
    RawIngestionPipelineMetricsEvent,
    RawNamingConventionEvent,
    RawOntologyShapeEvent,
    RawProcedurePatternEvent,
    RawQueryPatternShapeEvent,
    RawRelationshipSchemaEvent,
)
from ..events.subscriber import EventSubscriber
from ..schema.observation import DomainObservationEnvelope
from ..store.base import MetaStore
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
from .tenant_config import TenantSignatureConfig


_logger = logging.getLogger(__name__)


class CollectorOutcome(str, Enum):
    """Per-event outcome — drives test assertions and metrics counters."""

    ACCEPTED = "accepted"          # passed everything; written to meta store
    OPT_OUT_DROPPED = "opt_out_dropped"  # opt-out gate
    SIGNATURE_FAILED = "signature_failed"  # compute_* raised, or envelope invalid
    CHECKER_REJECTED = "checker_rejected"  # static checker pipeline rejected


@dataclass(frozen=True)
class CollectorResult:
    """What happened to one raw event.

    `payload_hash` is set on every outcome (we hash the raw-event dict on
    drops so the audit log entry can be correlated forensically). On
    ACCEPTED outcomes, `envelope` carries the wire payload that landed in
    the meta store.
    """

    outcome: CollectorOutcome
    payload_hash: str
    reason_code: Optional[ReasonCode] = None
    stage: Optional[Stage] = None
    envelope: Optional[DomainObservationEnvelope] = None


# ---------------------------------------------------------------------------
# Dispatch table — single compute_* per raw event variant
# ---------------------------------------------------------------------------


# Maps the raw-event class to its `compute_<variant>` function. We use the
# class (not the `kind` string) so a stray Literal mismatch upstream can't
# select the wrong compute_*.
_COMPUTE_DISPATCH = {
    RawOntologyShapeEvent: compute_ontology_shape,
    RawNamingConventionEvent: compute_naming_convention,
    RawDocumentTypeDistributionEvent: compute_document_type_distribution,
    RawRelationshipSchemaEvent: compute_relationship_schema,
    RawProcedurePatternEvent: compute_procedure_pattern,
    RawQueryPatternShapeEvent: compute_query_pattern_shape,
    RawClassifierUncertaintyEvent: compute_classifier_uncertainty,
    RawIngestionPipelineMetricsEvent: compute_ingestion_pipeline_metrics,
}


class SignatureCollector:
    """Per-tenant collector.

    Wire one of these up per tenant ingestion worker. Construction is cheap;
    the heavy state is the `CheckerPipeline` instance (spaCy model). Share
    a pipeline across tenants by passing the same instance in.
    """

    def __init__(
        self,
        *,
        tenant_config: TenantSignatureConfig,
        meta_store: MetaStore,
        audit_log: TenantAuditLog,
        pipeline: Optional[CheckerPipeline] = None,
    ) -> None:
        self._tenant_config = tenant_config
        self._meta_store = meta_store
        self._audit_log = audit_log
        self._pipeline = pipeline or CheckerPipeline()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, subscriber: EventSubscriber) -> list[CollectorResult]:
        """Drain `subscriber` until end-of-stream, processing each event.

        Returns the per-event result list — useful for tests; production
        callers can discard the return value.
        """

        results: list[CollectorResult] = []
        async for raw in subscriber.iter_events():
            result = await self.process_one(raw)
            results.append(result)
        return results

    async def stream(
        self, subscriber: EventSubscriber
    ) -> AsyncIterator[CollectorResult]:
        """Streaming variant of `run` — yields each result as it lands.

        Tests use this when they want to inspect partial state without
        waiting for end-of-stream.
        """

        async for raw in subscriber.iter_events():
            yield await self.process_one(raw)

    async def process_one(self, raw) -> CollectorResult:
        """Run the full per-event state machine. Single source of truth."""

        return await self._process(raw)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    async def _process(self, raw) -> CollectorResult:
        # --- Opt-out gate (M1-MCP-05). ---
        if self._tenant_config.opt_out:
            payload_hash = _compute_payload_hash(_safe_dump(raw))
            self._audit_log.write(
                payload_hash=payload_hash,
                reason_code=ReasonCode.OPT_OUT,
                stage=Stage.OPT_OUT_GATE,
            )
            _logger.info(
                "collector: opt_out drop", extra={"payload_hash": payload_hash}
            )
            return CollectorResult(
                outcome=CollectorOutcome.OPT_OUT_DROPPED,
                payload_hash=payload_hash,
                reason_code=ReasonCode.OPT_OUT,
                stage=Stage.OPT_OUT_GATE,
            )

        # --- Compute signature payload from raw event. ---
        compute_fn = _COMPUTE_DISPATCH.get(type(raw))
        if compute_fn is None:
            # Unknown raw-event class. Treat as a signature failure (the
            # ingestion service emitted something the collector doesn't
            # know how to translate).
            payload_hash = _compute_payload_hash(_safe_dump(raw))
            self._audit_log.write(
                payload_hash=payload_hash,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                stage=Stage.SCHEMA_VALIDATE,
            )
            _logger.warning(
                "collector: unknown raw event type",
                extra={"payload_hash": payload_hash, "type": type(raw).__name__},
            )
            return CollectorResult(
                outcome=CollectorOutcome.SIGNATURE_FAILED,
                payload_hash=payload_hash,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                stage=Stage.SCHEMA_VALIDATE,
            )

        try:
            payload = compute_fn(raw, self._tenant_config)
        except (ValidationError, ValueError, TypeError) as exc:
            payload_hash = _compute_payload_hash(_safe_dump(raw))
            self._audit_log.write(
                payload_hash=payload_hash,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                stage=Stage.SCHEMA_VALIDATE,
            )
            _logger.warning(
                "collector: signature compute failed",
                extra={
                    "payload_hash": payload_hash,
                    # The exception type only — never the .args / message,
                    # which could echo a field value.
                    "exc_type": type(exc).__name__,
                },
            )
            return CollectorResult(
                outcome=CollectorOutcome.SIGNATURE_FAILED,
                payload_hash=payload_hash,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                stage=Stage.SCHEMA_VALIDATE,
            )

        # --- Build envelope. ---
        try:
            envelope = DomainObservationEnvelope(
                event_id=uuid.uuid4(),
                schema_version="1.0.0",
                observed_at_utc=datetime.now(timezone.utc),
                tenant_anon_id=self._tenant_config.tenant_anon_id,
                opt_out_flag=False,
                domain_signature_id=None,
                payload=payload,
            )
        except ValidationError as exc:
            payload_hash = _compute_payload_hash(_safe_dump(raw))
            self._audit_log.write(
                payload_hash=payload_hash,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                stage=Stage.SCHEMA_VALIDATE,
            )
            _logger.warning(
                "collector: envelope build failed",
                extra={
                    "payload_hash": payload_hash,
                    "exc_type": type(exc).__name__,
                },
            )
            return CollectorResult(
                outcome=CollectorOutcome.SIGNATURE_FAILED,
                payload_hash=payload_hash,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                stage=Stage.SCHEMA_VALIDATE,
            )

        # --- Run the static checker pipeline (the gate). ---
        envelope_dict = envelope.model_dump(mode="json")
        chain = self._pipeline.check(envelope_dict)

        if not chain.passed:
            self._audit_log.write(
                payload_hash=chain.payload_hash,
                reason_code=chain.failed_reason or ReasonCode.SCHEMA_VALIDATION_FAILED,
                stage=chain.failed_stage or Stage.SCHEMA_VALIDATE,
            )
            _logger.info(
                "collector: checker rejected",
                extra={
                    "payload_hash": chain.payload_hash,
                    "stage": chain.failed_stage.value if chain.failed_stage else None,
                    "reason": chain.failed_reason.value if chain.failed_reason else None,
                },
            )
            return CollectorResult(
                outcome=CollectorOutcome.CHECKER_REJECTED,
                payload_hash=chain.payload_hash,
                reason_code=chain.failed_reason,
                stage=chain.failed_stage,
            )

        # --- Persist to meta store. ---
        await self._meta_store.write_observation(envelope)
        _logger.info(
            "collector: accepted",
            extra={"payload_hash": chain.payload_hash},
        )
        return CollectorResult(
            outcome=CollectorOutcome.ACCEPTED,
            payload_hash=chain.payload_hash,
            envelope=envelope,
        )


def _safe_dump(raw) -> dict:
    """Coerce a raw event (or unknown object) to a JSON-able dict for hashing.

    Used only to produce a `payload_hash` for the audit log. The dict is
    *not* persisted anywhere — it lives just long enough to be sha256'd.
    """

    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json")
    # Defensive fallback — should never happen given the Pydantic discriminated
    # union, but if a caller hands us a plain dict we still want a stable hash.
    if isinstance(raw, dict):
        return raw
    return {"_repr": repr(raw)}

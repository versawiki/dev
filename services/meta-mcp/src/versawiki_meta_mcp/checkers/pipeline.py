"""The 5+1-stage static-checker pipeline.

Order (first hard failure short-circuits):
  1. schema_validate
  2. forbidden_field_name_scan
  3. pii_ner
  4. numeric_pattern
  5. quote_near_quote
  6. opt_out_gate

This module is intentionally small — the heavy lifting lives in the
individual stage modules. Keeping the pipeline narrow makes it easy to
audit and unit-test the *ordering* invariant: ordering is itself
load-bearing because each stage's preconditions depend on the previous
stage's guarantees (e.g. stage 3 trusts that stage 1 has produced a
valid envelope with known string fields).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from pydantic import ValidationError

from ..schema.observation import DomainObservationEnvelope
from .forbidden_fields import scan_forbidden_field_names
from .numeric import scan_numeric_pattern
from .pii import PIIChecker
from .quotes import CorpusShinglesFn, scan_quotes
from .results import ChainResult, CheckResult, ReasonCode, Stage


def _compute_payload_hash(serialized: dict[str, Any]) -> str:
    """Stable sha256 over the canonical JSON of the (rejected) event.

    Used in the audit log so we can identify *which* event was rejected
    without storing the offending payload. Sorting keys ensures the hash
    is stable across producers.
    """

    canonical = json.dumps(serialized, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CheckerPipeline:
    """Runs the static-checker stages in the order from spec §5.2.

    Construct once per ingestion worker (the spaCy model load is the
    expensive part). Pipeline instances are reusable and stateless aside
    from the lazily-cached spaCy model inside `PIIChecker`.
    """

    def __init__(
        self,
        *,
        pii_checker: Optional[PIIChecker] = None,
        corpus_shingles_fn: Optional[CorpusShinglesFn] = None,
    ) -> None:
        self._pii = pii_checker or PIIChecker()
        self._corpus_shingles_fn = corpus_shingles_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, raw_event: dict[str, Any]) -> ChainResult:
        """Run every stage on `raw_event`. First hard failure short-circuits.

        `raw_event` must be a dict (deserialized JSON). We deliberately do
        not accept an already-constructed envelope as input because then
        stage 1 (schema validation) would have nothing to check.
        """

        results: list[CheckResult] = []
        payload_hash = _compute_payload_hash(raw_event)

        # --- Stage 1: schema validate ---
        try:
            envelope = DomainObservationEnvelope.model_validate(raw_event)
        except ValidationError as exc:
            results.append(
                CheckResult(
                    stage=Stage.SCHEMA_VALIDATE,
                    passed=False,
                    reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                    # Pydantic error count + first error type, no values.
                    details=(
                        f"{exc.error_count()} pydantic error(s); "
                        f"first: {exc.errors()[0]['type'] if exc.errors() else 'unknown'}"
                    ),
                )
            )
            return ChainResult(
                passed=False,
                failed_stage=Stage.SCHEMA_VALIDATE,
                failed_reason=ReasonCode.SCHEMA_VALIDATION_FAILED,
                results=results,
                payload_hash=payload_hash,
            )
        results.append(CheckResult(stage=Stage.SCHEMA_VALIDATE, passed=True))

        # The validated envelope is our re-serialized source of truth for
        # later stages — this strips any unknown fields the model would
        # have rejected anyway and gives us a known-shape dict to walk.
        serialized = envelope.model_dump(mode="json")

        # --- Stage 2: forbidden field name scan ---
        r2 = scan_forbidden_field_names(serialized)
        results.append(r2)
        if not r2.passed:
            return ChainResult(
                passed=False,
                failed_stage=r2.stage,
                failed_reason=r2.reason_code,
                results=results,
                payload_hash=payload_hash,
            )

        # --- Stage 3: PII / NER ---
        r3 = self._pii.check(serialized)
        results.append(r3)
        if not r3.passed:
            return ChainResult(
                passed=False,
                failed_stage=r3.stage,
                failed_reason=r3.reason_code,
                results=results,
                payload_hash=payload_hash,
            )

        # --- Stage 4: numeric pattern ---
        r4 = scan_numeric_pattern(serialized)
        results.append(r4)
        if not r4.passed:
            return ChainResult(
                passed=False,
                failed_stage=r4.stage,
                failed_reason=r4.reason_code,
                results=results,
                payload_hash=payload_hash,
            )

        # --- Stage 5: quote / near-quote ---
        r5 = scan_quotes(serialized, corpus_shingles_fn=self._corpus_shingles_fn)
        results.append(r5)
        if not r5.passed:
            return ChainResult(
                passed=False,
                failed_stage=r5.stage,
                failed_reason=r5.reason_code,
                results=results,
                payload_hash=payload_hash,
            )

        # --- Stage 6: opt-out gate ---
        # Per spec §5.2 step 6 and §5.4: if opt_out_flag is True, the meta
        # store insertion is rejected (the tenant-local audit log still
        # records the envelope). We treat that as a "passed but blocked"
        # outcome: the chain returns `passed=False, failed_reason=OPT_OUT`
        # so callers can distinguish from real privacy failures.
        if envelope.opt_out_flag:
            r6 = CheckResult(
                stage=Stage.OPT_OUT_GATE,
                passed=False,
                reason_code=ReasonCode.OPT_OUT,
                details="tenant opted out; meta-store insertion blocked",
            )
            results.append(r6)
            return ChainResult(
                passed=False,
                failed_stage=Stage.OPT_OUT_GATE,
                failed_reason=ReasonCode.OPT_OUT,
                results=results,
                payload_hash=payload_hash,
            )
        results.append(CheckResult(stage=Stage.OPT_OUT_GATE, passed=True))

        return ChainResult(
            passed=True,
            failed_stage=None,
            failed_reason=None,
            results=results,
            payload_hash=payload_hash,
        )


def run_static_checkers(
    raw_event: dict[str, Any],
    *,
    pipeline: Optional[CheckerPipeline] = None,
) -> ChainResult:
    """Convenience entrypoint. Builds a default pipeline if none provided."""

    return (pipeline or CheckerPipeline()).check(raw_event)

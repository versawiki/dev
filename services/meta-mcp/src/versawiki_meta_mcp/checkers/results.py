"""Result types for the checker pipeline.

The crucial design property: result objects must be safe to log. They carry
the *reason* and the *stage* but never the offending payload itself. The
audit log writer relies on this — see `audit.tenant_audit_log`.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Stage(str, Enum):
    """The fixed ordering of the static-checker pipeline (spec §5.2)."""

    SCHEMA_VALIDATE = "schema_validate"
    FORBIDDEN_FIELD_NAME_SCAN = "forbidden_field_name_scan"
    PII_NER = "pii_ner"
    NUMERIC_PATTERN = "numeric_pattern"
    QUOTE_NEAR_QUOTE = "quote_near_quote"
    OPT_OUT_GATE = "opt_out_gate"


class ReasonCode(str, Enum):
    """Stable reason codes; safe to write to audit logs and dashboards."""

    # stage 1
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"

    # stage 2
    FORBIDDEN_FIELD_NAME = "FORBIDDEN_FIELD_NAME"

    # stage 3
    NER_HIT_PERSON = "NER_HIT_PERSON"
    NER_HIT_ORG = "NER_HIT_ORG"
    NER_HIT_GPE = "NER_HIT_GPE"
    NER_HIT_EMAIL = "NER_HIT_EMAIL"
    NER_HIT_PHONE = "NER_HIT_PHONE"
    NER_HIT_SSN = "NER_HIT_SSN"
    NER_HIT_URL = "NER_HIT_URL"
    NER_HIT_GENERIC = "NER_HIT_GENERIC"

    # stage 4
    RAW_NUMERIC = "RAW_NUMERIC"

    # stage 5
    QUOTE_OVERLAP = "QUOTE_OVERLAP"
    STRING_TOO_LONG = "STRING_TOO_LONG"

    # stage 6
    OPT_OUT = "OPT_OUT"


class CheckResult(BaseModel):
    """One stage's verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Stage
    passed: bool
    reason_code: Optional[ReasonCode] = None
    # `details` is a short, content-free description (e.g. "field `name`
    # found at $.payload.kind_distribution.name"). Stage implementations
    # must NOT put offending payload bytes into this string.
    details: Optional[str] = None


class ChainResult(BaseModel):
    """The full pipeline verdict and per-stage trail."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    failed_stage: Optional[Stage] = None
    failed_reason: Optional[ReasonCode] = None
    results: list[CheckResult]
    # sha256 of the canonical JSON of the offending event. Computed by the
    # pipeline so the audit log can record *which* event was rejected
    # without storing its content.
    payload_hash: str

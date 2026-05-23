"""Tenant-local audit log for rejected DomainObservation events.

================================================================
PRIVACY INVARIANT (load-bearing — do not weaken without a DECISIONS entry)
================================================================

When the static-checker pipeline rejects an event, this module is the only
thing that persists a record of the rejection. The record contains EXACTLY:

    - payload_hash    (sha256 of canonical JSON of the offending event)
    - reason_code     (ReasonCode enum value)
    - stage           (Stage enum value or free string -- the failing stage)
    - timestamp       (ISO-8601 UTC when the audit record was written)

The offending payload itself is NEVER written. The hash exists so a
forensic comparison can prove "yes, that particular event was rejected"
without retaining the bytes that made it rejectable.

This module must remain the sole writer of `<tenant_dir>/audit.jsonl`.
If you find yourself adding a field that takes any portion of the event
payload (raw dict, model_dump, error message string, ValidationError
errors() list, ...), STOP — that is a privacy-boundary violation and
needs a DECISIONS.md entry and a re-review.

v2 (`M1-MCP-02`) will swap the JSONL file for a Postgres row, async,
inside the tenant schema. The invariant above carries over verbatim.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from ..checkers.results import ReasonCode, Stage


class TenantAuditLog:
    """Append-only JSONL writer for tenant-local audit records.

    Sync writes are fine for v1. The async wrapper lives in `M1-MCP-02`.
    Each `write` call appends exactly one JSON object on its own line.
    """

    def __init__(self, audit_path: Union[str, os.PathLike[str]]) -> None:
        """Construct an audit log bound to a specific JSONL file path.

        The parent directory must exist. The file is created on first
        write if it does not exist.
        """

        self._path = Path(audit_path)

    @property
    def path(self) -> Path:
        return self._path

    def write(
        self,
        payload_hash: str,
        reason_code: ReasonCode,
        stage: Union[Stage, str],
    ) -> None:
        """Append a single audit record.

        Args:
            payload_hash: sha256 hex digest of the canonical JSON of the
                offending event. Computed by the checker pipeline.
            reason_code: which reason code fired.
            stage: the pipeline stage that produced the rejection.

        The record is `{payload_hash, reason_code, stage, timestamp}` ONLY.
        Adding any field that carries payload bytes is forbidden — see the
        module docstring.
        """

        # Coerce enums to their string values for stable on-disk format.
        stage_str = stage.value if isinstance(stage, Stage) else str(stage)
        reason_str = (
            reason_code.value
            if isinstance(reason_code, ReasonCode)
            else str(reason_code)
        )

        record = {
            "payload_hash": payload_hash,
            "reason_code": reason_str,
            "stage": stage_str,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Append mode = 'a'. JSONL = one JSON object per line, no trailing
        # comma. We `flush()` to make the test's read-back deterministic;
        # the kernel's write-back is already synchronous for a single
        # short append.
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True))
            f.write("\n")
            f.flush()

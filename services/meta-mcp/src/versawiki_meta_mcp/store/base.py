"""`MetaStore` Protocol — the write/query interface every backend implements.

v1 (`FileMetaStore`) is JSONL on disk. v2 (`M1-MCP-02b`) will be Postgres
with the same Protocol. The signature collector knows only about this
Protocol, so swapping the backend doesn't reach the collector.

Query shape (`query`) is a sketch for `M1-MCP-04`: the skill applier needs
to find observations by `(tenant_anon_id, kind, time-range)` and by
`domain_signature_id`. The v1 file store implements a minimal subset
sufficient to write integration tests; the Postgres store will widen it.
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, Optional, Protocol, runtime_checkable

from ..schema.observation import DomainObservationEnvelope


@runtime_checkable
class MetaStore(Protocol):
    """Append + query interface for the meta-tenant observation store."""

    async def write_observation(self, env: DomainObservationEnvelope) -> None:
        """Persist one envelope. Append-only. Concurrency-safe."""
        ...

    async def query(
        self,
        *,
        tenant_anon_id: Optional[str] = None,
        kind: Optional[str] = None,
        since_utc: Optional[datetime] = None,
        until_utc: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[DomainObservationEnvelope]:  # pragma: no cover - Protocol
        """Stream observations matching the filter."""
        ...

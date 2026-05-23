"""Meta-tenant observation store.

Exactly one store is wired per meta-MCP process. v1 is JSONL on disk
(`FileMetaStore`); v2 (`M1-MCP-02b`) is Postgres-backed.

Privacy invariant: the store only ever sees a `DomainObservationEnvelope`,
which is `extra="forbid"` and has already passed the checker pipeline.
The store implementation MUST NOT attach side-channels (e.g., the raw
event, the offending bytes for rejections) — those don't belong in the
meta layer at all.
"""

from .base import MetaStore
from .file_store import FileMetaStore

__all__ = ["MetaStore", "FileMetaStore"]

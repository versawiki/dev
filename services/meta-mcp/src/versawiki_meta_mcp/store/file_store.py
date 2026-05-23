"""JSONL meta-store for v1.

Layout decision: ONE file per meta root: `<meta_root>/observations.jsonl`.
Rationale: the meta layer is *not* tenant-partitioned by design — its
whole point is to learn cross-tenant patterns. Splitting by
`tenant_anon_id` here would re-introduce a tenant-level partition where
none belongs. Queries that filter by tenant_anon_id (M1-MCP-04) read the
single file and filter in Python. v2 (Postgres) indexes the column.

Concurrency: writes use a process-level `asyncio.Lock` plus the OS file's
own O_APPEND semantics (POSIX `open(...,'a')` is atomic for writes <= PIPE_BUF
on Linux/macOS; the lock guards Windows and multi-line edge cases). Two
async tasks calling `write_observation` concurrently produce two complete
JSON-per-line records, never an interleaved one.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional, Union

from ..schema.observation import DomainObservationEnvelope


def _parse_iso_z(s: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp. Tolerant of `Z` suffix (Python <3.11
    `datetime.fromisoformat` chokes on it; Pydantic's `mode="json"` writes it).
    Returns None on parse failure.
    """

    if not s:
        return None
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


class FileMetaStore:
    """JSONL meta-store. Append-on-write, scan-on-query."""

    def __init__(self, meta_root: Union[str, os.PathLike[str]]) -> None:
        self._root = Path(meta_root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "observations.jsonl"
        # The lock is bound to the running loop. We deliberately construct it
        # lazily inside `write_observation` so the loop is the right one.
        self._lock: Optional[asyncio.Lock] = None

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def write_observation(self, env: DomainObservationEnvelope) -> None:
        """Append one envelope as a single JSONL line."""

        # The envelope is already `frozen=True, extra="forbid"`. `model_dump`
        # with `mode="json"` produces JSON-serializable Python primitives.
        record = env.model_dump(mode="json")
        line = json.dumps(record, sort_keys=True, default=str)

        lock = self._ensure_lock()
        async with lock:
            # Plain blocking file IO inside the lock. JSONL appends are
            # tiny; making this `asyncio.to_thread` would buy nothing in v1.
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")
                f.flush()

    async def query(
        self,
        *,
        tenant_anon_id: Optional[str] = None,
        kind: Optional[str] = None,
        since_utc: Optional[datetime] = None,
        until_utc: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[DomainObservationEnvelope]:
        """Stream matching observations. Linear scan — fine for v1.

        Filters are AND'd. `limit` caps yielded results.
        """

        if not self._path.exists():
            return

        yielded = 0
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # A corrupt line — skip rather than fail the whole query.
                    # v2 Postgres won't have this concern.
                    continue

                if tenant_anon_id and record.get("tenant_anon_id") != tenant_anon_id:
                    continue
                if kind:
                    pkind = (record.get("payload") or {}).get("kind")
                    if pkind != kind:
                        continue
                if since_utc or until_utc:
                    raw_ts = record.get("observed_at_utc")
                    if not raw_ts:
                        continue
                    ts = _parse_iso_z(raw_ts)
                    if ts is None:
                        continue
                    if since_utc and ts < since_utc:
                        continue
                    if until_utc and ts > until_utc:
                        continue

                try:
                    env = DomainObservationEnvelope.model_validate(record)
                except Exception:
                    # Same forgiving policy as JSONDecodeError above.
                    continue

                yield env
                yielded += 1
                if limit is not None and yielded >= limit:
                    return

    async def count(self) -> int:
        """Convenience: how many records are on disk."""

        if not self._path.exists():
            return 0
        n = 0
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
        return n

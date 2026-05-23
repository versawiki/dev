"""Append-only audit log with per-row hash chain.

Every interesting event in the orchestrator's lifecycle goes here:
trigger fired, agent run started, tool invoked, spend recorded, PR opened,
escalation sent, pause toggled. The hash chain makes tampering detectable —
if a row is altered or removed, the subsequent row's `prev_hash` no longer
matches.

SQLite is intentional: the orchestrator is a single process on one VM, and
SQLite gives us atomic appends, durability via WAL, and zero operational
overhead. When we move to multi-tenant operation we'll migrate to the
shared Postgres instance, but the API of `AuditLog` stays stable so the
swap is a single-file change.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


_GENESIS_HASH = "0" * 64


class AuditLogVerifyError(Exception):
    """Raised when the hash chain doesn't verify."""


@dataclass(frozen=True)
class AuditEntry:
    """One row in the audit log.

    `payload` is arbitrary JSON-serialisable structure — keep it small.
    The orchestrator pre-serializes large agent outputs and stores only
    references (e.g. PR URLs, commit SHAs) here.
    """

    id: int
    ts_ns: int  # nanoseconds since unix epoch
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = _GENESIS_HASH
    this_hash: str = ""

    @staticmethod
    def compute_hash(
        ts_ns: int,
        event_type: str,
        payload: dict[str, Any],
        prev_hash: str,
    ) -> str:
        """Compute the SHA-256 chain hash for a row.

        The hash is over a canonical encoding so reordering keys in
        `payload` doesn't change the result.
        """
        canonical = json.dumps(
            {"ts_ns": ts_ns, "event_type": event_type, "payload": payload, "prev_hash": prev_hash},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    """SQLite-backed append-only log.

    Thread-safe via a single internal mutex — the orchestrator writes from
    asyncio tasks but the SQLite connection itself is not asyncio-aware,
    so we serialize all writes through one connection.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # `isolation_level=None` -> autocommit; we manage transactions
        # explicitly. WAL gives us durable concurrent reads.
        self._conn = sqlite3.connect(
            str(self._db_path),
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ns      INTEGER NOT NULL,
                event_type TEXT    NOT NULL,
                payload    TEXT    NOT NULL,
                prev_hash  TEXT    NOT NULL,
                this_hash  TEXT    NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS audit_event_type_ix ON audit(event_type)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS audit_ts_ns_ix ON audit(ts_ns)")

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> AuditEntry:
        """Append a new audit entry. Returns the persisted row."""
        payload = payload or {}
        ts_ns = time.time_ns()
        with self._lock:
            cur = self._conn.execute("SELECT this_hash FROM audit ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            prev_hash = row[0] if row else _GENESIS_HASH
            this_hash = AuditEntry.compute_hash(ts_ns, event_type, payload, prev_hash)
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            cur = self._conn.execute(
                "INSERT INTO audit (ts_ns, event_type, payload, prev_hash, this_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts_ns, event_type, payload_json, prev_hash, this_hash),
            )
            row_id = cur.lastrowid
        assert row_id is not None
        return AuditEntry(
            id=row_id,
            ts_ns=ts_ns,
            event_type=event_type,
            payload=payload,
            prev_hash=prev_hash,
            this_hash=this_hash,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def tail(self, n: int = 50, event_type: str | None = None) -> list[AuditEntry]:
        """Most recent N entries (newest last)."""
        if event_type is None:
            cur = self._conn.execute(
                "SELECT id, ts_ns, event_type, payload, prev_hash, this_hash "
                "FROM audit ORDER BY id DESC LIMIT ?",
                (n,),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, ts_ns, event_type, payload, prev_hash, this_hash "
                "FROM audit WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                (event_type, n),
            )
        rows = cur.fetchall()
        rows.reverse()
        return [self._row_to_entry(r) for r in rows]

    def iter_all(self) -> Iterable[AuditEntry]:
        cur = self._conn.execute(
            "SELECT id, ts_ns, event_type, payload, prev_hash, this_hash FROM audit ORDER BY id ASC"
        )
        while True:
            row = cur.fetchone()
            if row is None:
                break
            yield self._row_to_entry(row)

    def count(self, event_type: str | None = None) -> int:
        if event_type is None:
            cur = self._conn.execute("SELECT COUNT(*) FROM audit")
        else:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM audit WHERE event_type = ?", (event_type,)
            )
        return int(cur.fetchone()[0])

    def sum_payload_numeric(
        self,
        event_type: str,
        key: str,
        *,
        since_ns: int | None = None,
    ) -> float:
        """Sum a numeric field from JSON payloads. Used by the spending tracker.

        SQLite JSON1 keeps this cheap even for tens of thousands of rows.
        """
        if since_ns is None:
            cur = self._conn.execute(
                f"SELECT COALESCE(SUM(CAST(json_extract(payload, '$.{key}') AS REAL)), 0.0) "
                "FROM audit WHERE event_type = ?",
                (event_type,),
            )
        else:
            cur = self._conn.execute(
                f"SELECT COALESCE(SUM(CAST(json_extract(payload, '$.{key}') AS REAL)), 0.0) "
                "FROM audit WHERE event_type = ? AND ts_ns >= ?",
                (event_type, since_ns),
            )
        return float(cur.fetchone()[0])

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify(self) -> int:
        """Walk the whole chain. Raise on any inconsistency.

        Returns the number of rows verified.
        """
        prev_hash = _GENESIS_HASH
        n = 0
        for entry in self.iter_all():
            expected = AuditEntry.compute_hash(
                entry.ts_ns, entry.event_type, entry.payload, prev_hash
            )
            if entry.prev_hash != prev_hash:
                raise AuditLogVerifyError(
                    f"row id={entry.id} prev_hash mismatch: stored={entry.prev_hash} "
                    f"expected={prev_hash}"
                )
            if entry.this_hash != expected:
                raise AuditLogVerifyError(
                    f"row id={entry.id} this_hash mismatch: stored={entry.this_hash} "
                    f"expected={expected}"
                )
            prev_hash = entry.this_hash
            n += 1
        return n

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: tuple) -> AuditEntry:
        rid, ts_ns, event_type, payload_json, prev_hash, this_hash = row
        return AuditEntry(
            id=int(rid),
            ts_ns=int(ts_ns),
            event_type=str(event_type),
            payload=json.loads(payload_json) if payload_json else {},
            prev_hash=str(prev_hash),
            this_hash=str(this_hash),
        )


def entry_as_dict(entry: AuditEntry) -> dict[str, Any]:
    """Convenience for serialising entries through the control API."""
    return asdict(entry)

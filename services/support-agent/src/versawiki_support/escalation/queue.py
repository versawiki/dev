"""Append-only escalation queue.

One JSON file per escalated conversation, written under
``escalations/<YYYY-MM-DD>/<conversation_id>.json``. The queue is
append-only on purpose: an escalation that landed yesterday must not
get retroactively rewritten by a later run.

If an escalation for the same conversation_id already exists in
today's bucket, we APPEND a numeric suffix instead of overwriting.
That preserves the audit trail even if the agent escalates twice for
related reasons.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


EscalationSeverity = Literal["low", "medium", "high", "critical"]


@dataclass
class EscalationEntry:
    """One escalation record."""

    conversation_id: str
    tenant_id: str | None
    channel: str
    reason: str
    severity: EscalationSeverity
    customer_identifier: str | None
    last_messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EscalationQueue:
    """Filesystem-backed append-only queue.

    The queue path is the root directory; one date-bucket subdir per
    UTC date. Reads scan the whole tree; v1 doesn't need an index.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _bucket_for(self, when: datetime | None = None) -> Path:
        when = when or datetime.now(timezone.utc)
        bucket = self.root / when.strftime("%Y-%m-%d")
        bucket.mkdir(parents=True, exist_ok=True)
        return bucket

    def append(self, entry: EscalationEntry) -> Path:
        """Write the entry and return its path.

        If the conversation already has an entry today, the new file
        gets a numeric suffix so prior entries are NEVER overwritten.
        """
        bucket = self._bucket_for()
        base = bucket / f"{entry.conversation_id}.json"
        path = base
        suffix = 1
        while path.exists():
            suffix += 1
            path = bucket / f"{entry.conversation_id}.{suffix}.json"
        path.write_text(
            json.dumps(entry.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def list_all(self) -> list[EscalationEntry]:
        """Walk every bucket and return entries in creation order."""
        if not self.root.exists():
            return []
        out: list[EscalationEntry] = []
        for bucket in sorted(self.root.iterdir()):
            if not bucket.is_dir():
                continue
            for path in sorted(bucket.glob("*.json")):
                raw = json.loads(path.read_text(encoding="utf-8"))
                out.append(EscalationEntry(**raw))
        return out


__all__ = ["EscalationQueue", "EscalationEntry", "EscalationSeverity"]

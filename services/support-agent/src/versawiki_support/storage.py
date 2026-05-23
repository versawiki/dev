"""Conversation persistence.

v1 = JSONL file per conversation (one line per snapshot). Production
swaps the same surface for Postgres rows in the tenant schema. The
public API is just :class:`ConversationStore`.

We snapshot on every ``save``; the JSONL grows over the life of a
conversation. Latest snapshot = last line. This makes audit
reconstruction trivial (replay forward) and keeps writes append-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .conversation import Conversation


class ConversationStore:
    """JSONL-per-conversation store."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, conv_id: str) -> Path:
        return self.root / f"{conv_id}.jsonl"

    def save(self, conv: Conversation) -> Path:
        path = self._path_for(conv.id)
        snapshot = conv.model_dump(mode="json")
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(snapshot, sort_keys=True) + "\n")
        return path

    def load(self, conv_id: str) -> Conversation | None:
        path = self._path_for(conv_id)
        if not path.exists():
            return None
        last_line = ""
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if line:
                    last_line = line
        if not last_line:
            return None
        return Conversation.model_validate_json(last_line)

    def history(self, conv_id: str) -> list[Conversation]:
        """Return every snapshot, oldest first. Useful for audit replay."""
        path = self._path_for(conv_id)
        if not path.exists():
            return []
        out: list[Conversation] = []
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                out.append(Conversation.model_validate_json(line))
        return out

    def list_ids(self) -> Iterable[str]:
        return (p.stem for p in sorted(self.root.glob("*.jsonl")))


__all__ = ["ConversationStore"]

"""Markdown knowledge-base loader.

Each KB article is a markdown file with YAML-ish frontmatter:

    ---
    name: API keys
    tags: [api-keys, auth, security]
    last_reviewed: 2026-05-23
    ---

    # API keys

    ... article body ...

The loader is deliberately minimal — no real YAML parser, just a
key:value scrape — because (a) we want zero non-stdlib deps in this
module, and (b) the format is owner-controlled (engineers write KB
files; not user-supplied content) so a strict parser is unnecessary.

Hot-reload: ``KnowledgeBase.maybe_reload()`` re-scans the directory if
any tracked file's mtime has advanced. Callers should invoke it before
each search if they need fresh content; the LLM agent does so on every
request because the cost is one ``stat`` per file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL,
)
_KV_RE = re.compile(r"^([a-zA-Z0-9_]+)\s*:\s*(.*)$")


def _parse_frontmatter(raw: str) -> tuple[dict[str, str | list[str]], str]:
    """Return ``(frontmatter_dict, body)``.

    Frontmatter is optional. If absent, returns ({}, raw).
    """
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    fm_raw, body = match.group(1), match.group(2)
    out: dict[str, str | list[str]] = {}
    for line in fm_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kv = _KV_RE.match(line)
        if not kv:
            continue
        key, value = kv.group(1), kv.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
            out[key] = [v for v in items if v]
        else:
            out[key] = value.strip("'\"")
    return out, body


@dataclass
class KBArticle:
    """One KB markdown file, parsed."""

    name: str
    tags: tuple[str, ...]
    last_reviewed: str | None
    body: str
    path: Path
    mtime_ns: int

    def matches(self, query: str) -> int:
        """Cheap relevance score: keyword overlap.

        Tokenises the query on non-word characters; counts hits in
        tags (weighted x3), name (x2), and body (x1). Lowercase
        match, stop words ignored (a tiny built-in list — anything
        more sophisticated belongs in retrieval, not the KB loader).
        """
        if not query.strip():
            return 0
        tokens = [t.lower() for t in re.split(r"\W+", query) if t]
        tokens = [t for t in tokens if t not in _STOP]
        if not tokens:
            return 0
        score = 0
        body_lc = self.body.lower()
        name_lc = self.name.lower()
        tag_lc = " ".join(self.tags).lower()
        for tok in tokens:
            if tok in tag_lc:
                score += 3
            if tok in name_lc:
                score += 2
            if tok in body_lc:
                score += 1
        return score


_STOP = frozenset(
    {
        "the", "a", "an", "of", "to", "and", "or", "but", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "for", "on", "in", "at", "by", "with",
        "from", "as", "it", "this", "that", "these", "those", "my",
        "your", "our", "their", "i", "we", "you", "they", "how",
        "what", "where", "when", "why", "can", "could", "would",
        "should", "if",
    }
)


@dataclass
class KnowledgeBase:
    """In-memory KB. Hot-reloadable via :meth:`maybe_reload`."""

    root: Path
    articles: list[KBArticle] = field(default_factory=list)

    @classmethod
    def load(cls, root: str | Path) -> "KnowledgeBase":
        kb = cls(root=Path(root))
        kb._reload()
        return kb

    def _reload(self) -> None:
        if not self.root.exists():
            self.articles = []
            return
        articles: list[KBArticle] = []
        for path in sorted(self.root.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            fm, body = _parse_frontmatter(raw)
            tags_raw = fm.get("tags", [])
            tags: tuple[str, ...]
            if isinstance(tags_raw, list):
                tags = tuple(tags_raw)
            elif isinstance(tags_raw, str):
                tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
            else:
                tags = ()
            name_val = fm.get("name") or path.stem
            assert isinstance(name_val, str)
            last_reviewed_val = fm.get("last_reviewed")
            last_reviewed = (
                last_reviewed_val if isinstance(last_reviewed_val, str) else None
            )
            articles.append(
                KBArticle(
                    name=name_val,
                    tags=tags,
                    last_reviewed=last_reviewed,
                    body=body.strip(),
                    path=path,
                    mtime_ns=path.stat().st_mtime_ns,
                )
            )
        self.articles = articles

    def maybe_reload(self) -> bool:
        """Re-scan if any tracked file changed (or new files exist).

        Returns True if a reload occurred.
        """
        if not self.root.exists():
            if self.articles:
                self.articles = []
                return True
            return False
        on_disk = {p: p.stat().st_mtime_ns for p in self.root.glob("*.md")}
        known = {a.path: a.mtime_ns for a in self.articles}
        if on_disk != known:
            self._reload()
            return True
        return False

    def search(self, query: str, *, limit: int = 3) -> list[KBArticle]:
        """Return the top-N matching articles, highest score first."""
        scored = [(a.matches(query), a) for a in self.articles]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:limit]]

    def get(self, name_or_stem: str) -> KBArticle | None:
        target = name_or_stem.lower()
        for a in self.articles:
            if a.name.lower() == target or a.path.stem.lower() == target:
                return a
        return None


__all__ = ["KnowledgeBase", "KBArticle"]

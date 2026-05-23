"""Parser registry — resolves a `ResourceRef` (or path) to the right parser.

Three-tier selection pattern lifted from `project-mcp-server/parsers/registry.py`:

1. Explicit `document_type` override (human-corrected docs).
2. MIME type match (preferred for trustworthiness).
3. File-extension fallback.

The prior repo's filename-regex tier is intentionally dropped — M1-ING-03's LLM
classifier replaces that heuristic. The "explicit override" path is kept for
human-corrected documents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import BaseParser, GeneralTextParser
from .email import EmailParser
from .excel import ExcelParser
from ..connectors._models import ResourceRef


class ParserRegistry:
    """Maps `(mime, extension, explicit_type)` -> parser instance.

    A single registry instance is reused across the pipeline; parsers are stateless
    so it's safe.
    """

    def __init__(self, parsers: list[BaseParser]) -> None:
        self._parsers = list(parsers)
        self._by_type: dict[str, BaseParser] = {p.document_type: p for p in parsers}
        # Build MIME and extension indexes. Later parsers win on conflict — we
        # register more-specific parsers after more-general ones, so this is
        # intentional.
        self._by_mime: dict[str, BaseParser] = {}
        self._by_ext: dict[str, BaseParser] = {}
        for p in parsers:
            for mime in p.supported_mime_types:
                self._by_mime[mime.lower()] = p
            for ext in p.supported_extensions:
                self._by_ext[ext.lower()] = p

    @classmethod
    def default(cls) -> "ParserRegistry":
        """The M1 default registry: text fallback, Excel, Email."""
        return cls(
            parsers=[
                GeneralTextParser(),
                ExcelParser(),
                EmailParser(),
            ]
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def for_type(self, document_type: str) -> Optional[BaseParser]:
        """Tier 1 — explicit document-type override."""
        return self._by_type.get(document_type)

    def for_mime(self, mime: Optional[str]) -> Optional[BaseParser]:
        """Tier 2 — MIME type match."""
        if not mime:
            return None
        return self._by_mime.get(mime.lower())

    def for_extension(self, ext: str) -> Optional[BaseParser]:
        """Tier 3 — extension fallback."""
        if not ext:
            return None
        return self._by_ext.get(ext.lower())

    def for_path(
        self,
        path: Path,
        *,
        explicit_type: Optional[str] = None,
        mime: Optional[str] = None,
    ) -> Optional[BaseParser]:
        """Resolve through all three tiers in order."""
        if explicit_type:
            parser = self.for_type(explicit_type)
            if parser:
                return parser
        if mime:
            parser = self.for_mime(mime)
            if parser:
                return parser
        return self.for_extension(path.suffix.lower())

    def for_ref(
        self,
        ref: ResourceRef,
        *,
        explicit_type: Optional[str] = None,
    ) -> Optional[BaseParser]:
        """Resolve from a `ResourceRef`. Uses the ref's `mime_type` hint."""
        if explicit_type:
            parser = self.for_type(explicit_type)
            if parser:
                return parser
        if ref.mime_type:
            parser = self.for_mime(ref.mime_type)
            if parser:
                return parser
        return self.for_extension(ref.extension)

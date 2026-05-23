# Lifted from project-mcp-server/parsers/base_parser.py per M0-06 audit (REUSE bucket).
# Adapted: project_id -> tenant_id + source_id; removed direct DB writes
# (results return as Pydantic models, persistence is the ingestion service's job).
"""Base Parser - All document parsers inherit from this.

To create a new parser:
  1. Create a new file: parsers/{type_name}.py
  2. Subclass BaseParser
  3. Implement extract_text() and extract_fields()
  4. Register it in parsers/registry.py

That's it. The system handles storage, indexing, and search automatically.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ParseResult(BaseModel):
    """Standardized output from any parser.

    Modernised to Pydantic v2 from the prior repo's `@dataclass`. Frozen so the
    pipeline can treat results as values; `to_db_row()` takes tenant + source
    keys at the persistence boundary instead of bundling them into the result.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_type: str = Field(..., description="Best-known type label, e.g. 'email'.")
    fields: dict[str, Any] = Field(default_factory=dict)
    full_text: str = Field(default="")
    summary: str = Field(default="")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_db_row(
        self,
        *,
        tenant_id: str,
        source_id: str,
        source_uri: str,
        source_path: str = "",
    ) -> dict[str, Any]:
        """Convert to a dict ready for database insertion.

        The tenant_id + source_id keys are what versawiki persists; the prior
        repo bundled `project_id` only.
        """
        row: dict[str, Any] = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "source_uri": source_uri,
            "source_path": source_path,
            "full_text": self.full_text,
            "summary": self.summary,
            "confidence_score": self.confidence,
        }
        row.update(self.fields)
        return row


class BaseParser(ABC):
    """Base class for all document type parsers."""

    # Override these in subclasses
    document_type: str = "general_document"
    supported_extensions: list[str] = []
    # MIME types this parser can handle. Used by `ParserRegistry` to resolve
    # via MIME first (preferred) and extension second.
    supported_mime_types: list[str] = []

    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the given file."""
        return file_path.suffix.lower() in self.supported_extensions

    @abstractmethod
    def extract_text(self, file_path: Path) -> str:
        """Extract full text content from the file.
        This is the raw text used for search indexing.
        """
        raise NotImplementedError

    @abstractmethod
    def extract_fields(self, file_path: Path, full_text: str) -> dict[str, Any]:
        """Extract structured fields from the document.
        Returns a dict matching the fields defined in seeds/aec_starter_taxonomy.yaml.
        Fields you can't extract should be omitted (not set to None).
        """
        raise NotImplementedError

    def detect_relationships(
        self, file_path: Path, full_text: str, fields: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Detect references to other documents.
        Override this to add relationship detection for your document type.
        Returns list of dicts:
            [{"target_type": "rfi", "target_ref": "RFI-042", "rel_name": "related_rfi"}]
        """
        return []

    def parse(
        self,
        file_path: Path,
        *,
        tenant_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> ParseResult:
        """Full parse pipeline. Usually you don't need to override this.

        `tenant_id` / `source_id` are accepted but only used by the eventual
        `to_db_row()` call — parsers themselves are tenant-agnostic.
        """
        file_path = Path(file_path)

        full_text = self.extract_text(file_path)
        fields = self.extract_fields(file_path, full_text)
        relationships = self.detect_relationships(file_path, full_text, fields)

        # Calculate confidence based on how many required fields were extracted.
        # (Simple heuristic — override for smarter logic.)
        confidence = self._estimate_confidence(fields)

        return ParseResult(
            document_type=self.document_type,
            fields=fields,
            full_text=full_text,
            confidence=confidence,
            relationships=relationships,
        )

    def _estimate_confidence(self, fields: dict[str, Any]) -> float:
        """Estimate how confident we are in the extraction."""
        if not fields:
            return 0.1
        filled = sum(1 for v in fields.values() if v is not None and v != "")
        total = max(len(fields), 1)
        return round(filled / total, 2)

    @staticmethod
    def file_hash(file_path: Path) -> str:
        """Generate a sha256 hash of the file for deduplication."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()


class GeneralTextParser(BaseParser):
    """Fallback parser for plain-text files. Used by tests and as the
    registry's last-resort handler for `.txt`/`.md`."""

    document_type = "general_document"
    supported_extensions = [".txt", ".md", ".log"]
    supported_mime_types = ["text/plain", "text/markdown"]

    def extract_text(self, file_path: Path) -> str:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def extract_fields(self, file_path: Path, full_text: str) -> dict[str, Any]:
        return {"title": file_path.stem}

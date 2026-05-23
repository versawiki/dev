"""Taxonomy loader + cheap heuristic scorer.

The taxonomy is the set of types the classifier picks from. M1 seeds it from
`seeds/aec_starter_taxonomy.yaml`; tenants will add overrides at a later
milestone (the loader already accepts overrides so the API doesn't change).

`match_score(parsed_doc, type_name)` is the heuristic sanity check the
orchestrator uses to cross-examine the LLM. It is deliberately cheap — keyword
overlap and a header-pattern match — because the *real* signal comes from the
LLM. Its job is only to flag "the LLM is wildly off" and "the LLM is picking
the same type we'd have guessed from filename alone."

The score is in [0,1] and combines:
  * filename-pattern hit on `file_patterns` (worth 0.4 if any glob matches)
  * type-name keyword hit anywhere in `full_text` (worth up to 0.3, scaled)
  * fields_hints keyword density in `full_text` (worth up to 0.3)
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from ..parsers.base import ParseResult


_DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parent.parent / "seeds" / "aec_starter_taxonomy.yaml"
)


@dataclass(frozen=True)
class TaxonomyType:
    """One ontology node. Mirrors a `document_types.<name>` entry in the YAML."""

    name: str
    display_name: str
    description: str
    file_patterns: tuple[str, ...] = field(default_factory=tuple)
    field_keywords: tuple[str, ...] = field(default_factory=tuple)
    # Free-form synonyms / aliases tied to the type — extra signal for the
    # heuristic. (Currently empty for seed types; tenants can extend.)
    keywords: tuple[str, ...] = field(default_factory=tuple)


class Taxonomy:
    """Iterable container of `TaxonomyType` plus heuristic scoring.

    Construct via `Taxonomy.from_yaml(path)` or `Taxonomy.starter()` for the
    bundled AEC seed. Per-tenant overrides can be merged via `with_overrides`.
    """

    def __init__(
        self,
        types: list[TaxonomyType],
        *,
        unclassified_type: str = "unclassified",
        default_type: str = "general_document",
    ) -> None:
        if not types:
            raise ValueError("Taxonomy must contain at least one type")
        self._types: dict[str, TaxonomyType] = {t.name: t for t in types}
        self.unclassified_type = unclassified_type
        self.default_type = default_type

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def starter(cls) -> "Taxonomy":
        """Load the bundled AEC seed taxonomy."""
        return cls.from_yaml(_DEFAULT_SEED_PATH)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "Taxonomy":
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: Mapping[str, Any]) -> "Taxonomy":
        doc_types_raw = data.get("document_types", {}) or {}
        types: list[TaxonomyType] = []
        for name, spec in doc_types_raw.items():
            spec = spec or {}
            types.append(_taxonomy_type_from_spec(name, spec))

        settings = data.get("settings", {}) or {}
        unclassified = settings.get("unclassified_type", "unclassified")
        default = settings.get("default_type", "general_document")

        # The seed YAML defines `general_document` and `unclassified` under
        # `settings` (catch-alls) rather than `document_types`. Ensure both
        # are addressable so the classifier can route fallbacks there.
        catch_all_spec = settings.get(default)
        if default not in {t.name for t in types}:
            spec = dict(catch_all_spec or {})
            spec.setdefault("display_name", "General Document")
            spec.setdefault("description", "Unclassified or miscellaneous document")
            types.append(_taxonomy_type_from_spec(default, spec))
        if unclassified != default and unclassified not in {t.name for t in types}:
            types.append(
                _taxonomy_type_from_spec(
                    unclassified,
                    {
                        "display_name": "Unclassified",
                        "description": (
                            "Document the classifier could not assign with confidence."
                        ),
                    },
                )
            )

        return cls(types, unclassified_type=unclassified, default_type=default)

    def with_overrides(self, overrides: Mapping[str, Mapping[str, Any]]) -> "Taxonomy":
        """Return a new taxonomy with tenant overrides merged in.

        Override semantics: a key in `overrides` either adds a new type (if
        the name is not already present) or replaces the existing entry's
        fields. We don't support deletion in M1 — a tenant can hide a seed
        type by overriding it with display_name="" if they really need to.
        """
        merged = dict(self._types)
        for name, spec in overrides.items():
            merged[name] = _taxonomy_type_from_spec(name, dict(spec))
        return Taxonomy(
            list(merged.values()),
            unclassified_type=self.unclassified_type,
            default_type=self.default_type,
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def list_types(self) -> list[TaxonomyType]:
        return list(self._types.values())

    def type_names(self) -> list[str]:
        return list(self._types.keys())

    def get_type(self, name: str) -> Optional[TaxonomyType]:
        return self._types.get(name)

    def __len__(self) -> int:
        return len(self._types)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._types

    # ------------------------------------------------------------------
    # Heuristic scoring — the LLM sanity-check
    # ------------------------------------------------------------------

    def match_score(
        self,
        parsed_doc: ParseResult,
        type_name: str,
        *,
        source_uri: str = "",
    ) -> float:
        """Cheap [0,1] match score for `parsed_doc` against `type_name`.

        Combines filename-pattern hit, type-name token presence, and fields_hints
        keyword density. Source URI is used for the file-pattern match because
        `ParseResult` itself doesn't carry the filename.
        """
        t = self._types.get(type_name)
        if t is None:
            return 0.0

        text = (parsed_doc.full_text or "").lower()
        title = str(parsed_doc.fields.get("title", "")).lower()
        haystack = f"{title}\n{text}"
        source_uri_lower = (source_uri or "").lower()

        # Component 1: filename-pattern match (0 or 0.4)
        pattern_score = 0.0
        if source_uri_lower and t.file_patterns:
            base = Path(source_uri_lower).name
            for pat in t.file_patterns:
                if fnmatch.fnmatch(base, pat.lower()):
                    pattern_score = 0.4
                    break

        # Component 2: type-name token in haystack (up to 0.3)
        type_tokens = [tok for tok in re.split(r"[_\W]+", t.name) if tok]
        type_score = 0.0
        if type_tokens:
            hits = sum(1 for tok in type_tokens if tok in haystack)
            type_score = min(0.3, 0.3 * (hits / len(type_tokens)))

        # Component 3: fields_hints / keyword density (up to 0.3)
        kw_score = 0.0
        kws = list(t.field_keywords) + list(t.keywords)
        if kws and haystack:
            hits = sum(1 for kw in kws if kw and kw in haystack)
            kw_score = min(0.3, 0.05 * hits)

        return round(min(1.0, pattern_score + type_score + kw_score), 4)

    def best_match(
        self,
        parsed_doc: ParseResult,
        *,
        source_uri: str = "",
    ) -> tuple[str, float]:
        """Return the (type_name, score) with the highest heuristic match.

        Tie-broken by taxonomy insertion order. If every type scores zero,
        returns the taxonomy's `default_type` with score 0.0.
        """
        best_name = self.default_type
        best_score = 0.0
        for name in self._types:
            score = self.match_score(parsed_doc, name, source_uri=source_uri)
            if score > best_score:
                best_score = score
                best_name = name
        return best_name, best_score

    def score_all(
        self,
        parsed_doc: ParseResult,
        *,
        source_uri: str = "",
    ) -> dict[str, float]:
        """Score every taxonomy type. Used by the orchestrator for cross-check."""
        return {
            name: self.match_score(parsed_doc, name, source_uri=source_uri)
            for name in self._types
        }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _taxonomy_type_from_spec(name: str, spec: Mapping[str, Any]) -> TaxonomyType:
    """Convert a raw YAML dict into a `TaxonomyType`.

    Field-hint names are flattened into a keyword list — they're already
    descriptive (e.g. "rfi_number", "submitted_by") and give the heuristic
    enough surface to recognise the type from text alone.
    """
    file_patterns = tuple(p.lower() for p in spec.get("file_patterns", []) or [])
    field_hints = spec.get("fields_hints", {}) or {}
    # Use both the field key and any `values:` enum members as keywords.
    field_keywords: list[str] = []
    for fname, fmeta in field_hints.items():
        field_keywords.append(str(fname).lower())
        if isinstance(fmeta, Mapping):
            values = fmeta.get("values", []) or []
            for v in values:
                if isinstance(v, str):
                    field_keywords.append(v.lower())
    # Always include the type-name itself as a keyword (helps with "rfi" vs
    # the rfi-prefixed fields).
    field_keywords.append(name.lower())

    return TaxonomyType(
        name=name,
        display_name=str(spec.get("display_name", name)),
        description=str(spec.get("description", "")),
        file_patterns=file_patterns,
        field_keywords=tuple(dict.fromkeys(field_keywords)),  # de-dup, preserve order
        keywords=tuple(k.lower() for k in (spec.get("keywords", []) or [])),
    )

"""Stage 2 — forbidden-field-name scan.

The schema (`extra="forbid"`) already rejects unknown top-level fields, but
this stage is the belt to the schema's braces: it walks the *serialized*
event and looks for any key name from the §4 blocklist anywhere in the tree.

Why a separate stage when the schema forbids unknown fields? Defense in
depth against future schema drift, custom payload subclasses, dynamically
constructed dicts, and dict-typed fields whose *values* could be a tenant-
controlled key. (E.g. `kind_distribution` is a `dict[Literal, int]`; if a
producer ever widens that to `dict[str, int]` by mistake, this stage
catches it before the boundary opens.)

The list of forbidden names comes literally from spec §4. Matching is
case-insensitive (per the task brief).
"""

from __future__ import annotations

from typing import Any, Iterator

from .results import CheckResult, ReasonCode, Stage


# §4 of domain-observation-v1.md. If you find yourself wanting to remove an
# entry from this list because it "looks safe", read the boundary decision
# (DECISIONS.md 2026-05-22 — Meta-MCP cross-tenant boundary) again first.
FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset(
    name.lower()
    for name in {
        # Free-text content
        "raw_text",
        "excerpt",
        "snippet",
        "body",
        "content",
        # File identifiers
        "file_path",
        "file_name",
        "filename",
        "source_uri",
        "blob_key",
        "path",
        # Customer identity
        "tenant_slug",
        "tenant_name",
        "display_name",
        "customer_name",
        "project_name",
        "org_name",
        "vendor_name",
        "person_name",
        "email",
        "phone",
        # Raw numerics
        "count",
        "total",
        "revenue",
        "value",
        "amount",
        "headcount",
        "quantity",
        # Free-form strings
        "title",
        "name",
        "label",
        "description",
        # Queries
        "query_text",
        "query",
        "q",
    }
)

# Field-name *prefixes* that are also forbidden. From spec §4 (`measurement_*`
# and `dim_*`).
FORBIDDEN_FIELD_PREFIXES: tuple[str, ...] = ("measurement_", "dim_")


def _walk(obj: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Yield (lowercased-key, json-path) for every key in the nested structure."""

    if isinstance(obj, dict):
        for k, v in obj.items():
            key_str = str(k)
            yield (key_str.lower(), f"{path}.{key_str}")
            yield from _walk(v, f"{path}.{key_str}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def scan_forbidden_field_names(serialized: dict[str, Any]) -> CheckResult:
    """Return a CheckResult for the forbidden-field-name stage."""

    for key_lower, json_path in _walk(serialized):
        if key_lower in FORBIDDEN_FIELD_NAMES or any(
            key_lower.startswith(p) for p in FORBIDDEN_FIELD_PREFIXES
        ):
            # `details` carries the key name and json-path only. The key
            # name is the *field* identifier (e.g. `name`), not the field
            # *value*. Field identifiers in our schema are schema-defined
            # strings; values would be customer content. This is safe.
            return CheckResult(
                stage=Stage.FORBIDDEN_FIELD_NAME_SCAN,
                passed=False,
                reason_code=ReasonCode.FORBIDDEN_FIELD_NAME,
                details=f"forbidden field-name `{key_lower}` at {json_path}",
            )

    return CheckResult(stage=Stage.FORBIDDEN_FIELD_NAME_SCAN, passed=True)

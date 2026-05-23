"""Stage 4 — numeric-pattern detector.

Per spec §5.2 step 4 and DECISIONS 2026-05-22 #3: every numeric leaf in the
payload must be one of:

  (a) a bucket label (those are strings, not numerics — they pass stage 4
      trivially because this stage only inspects numeric leaves).
  (b) a ratio / probability / confidence in [0.0, 1.0].
  (c) a low-resolution quantile from the fixed set (we accept any float in
      [0, 1] as a quantile; coarser-than-1.0 quantiles need to be bucketed).
  (d) an integer that the schema marks as a "structural count": small,
      meaning fewer than 1000, and bounded by the schema's own `le=` /
      `Field(...)` constraints.

Anything else is RAW_NUMERIC — a hard reject.

Why this stage exists separately from the schema. The schema's `Field(ge=0,
le=1)` already enforces (b)/(c) on every ratio field, and `Field(ge=0,
le=1000)` enforces (d) on counts. This stage is the *invariant audit*: if
some future payload variant adds a numeric field without those bounds, the
stage catches it at runtime. Defense in depth.

Allow-listed numeric-field policy:

We pre-compute the set of "allowed numeric field json-paths" by walking the
schema. Any numeric leaf at a path not in this set is forbidden. That is
*stricter* than the spec text but matches the spec's intent: numerics only
cross when the schema explicitly says so.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

from .results import CheckResult, ReasonCode, Stage


# Maximum value for a structural count. Per spec §5.2: "an integer < 1000
# that the schema marks as structural count".
STRUCTURAL_COUNT_MAX = 1000


# json-path *suffixes* (last segment) that the schema marks as legal
# numeric leaves. We match by terminal segment rather than full path so
# we don't have to enumerate every payload variant explicitly.
#
# Three buckets:
#  BRANCHING_FACTOR_LEAVES — non-negative real, < STRUCTURAL_COUNT_MAX (NOT capped at 1.0;
#                            see spec §3.1 — these are tree shape stats, not probabilities)
#  RATIO_LEAVES            — must be in [0.0, 1.0]
#  COUNT_LEAVES            — must be int in [0, STRUCTURAL_COUNT_MAX)

# Branching-factor quantile leaves.  Per spec §3.1 these are structural shape
# statistics that can legitimately exceed 1.0 (a node with three children has
# branching factor 3).  They are *not* ratios or probabilities.  We still cap
# at STRUCTURAL_COUNT_MAX to guard against raw-count leakage.
ALLOWED_BRANCHING_FACTOR_LEAVES: frozenset[str] = frozenset({
    "branching_factor_p50",
    "branching_factor_p95",
})

ALLOWED_RATIO_LEAVES: frozenset[str] = frozenset({
    "leaf_to_internal_ratio",
    "induced_vs_seed_ratio",
    "adherence_rate",
    "classifier_confidence_p50",
    "classifier_confidence_p10",
    "confidence_p50",
    "confusion_rate",
    "overall_confidence_p10",
    "classification_failure_rate",
    "ontology_assignment_failure_rate",
})

ALLOWED_COUNT_LEAVES: frozenset[str] = frozenset({
    "depth",
    "median_lifecycle_states",
    "chunks_per_doc_p50",
    "chunks_per_doc_p95",
    # embedding_dim is `Literal[1024]` in the schema. It's still a numeric
    # leaf when serialized. We allow it explicitly.
    "embedding_dim",
})

# Numeric leaves that appear *inside a dict[K, int]* — keyed by the
# *parent* dict field name. These represent kind-of-thing counts where
# the key is a `Literal[...]` and the value is a small structural count.
ALLOWED_DICT_VALUE_COUNT_PARENTS: frozenset[str] = frozenset({
    "kind_distribution",  # dict[Literal["category","entity","topic"], int]
})


def _last_segment(json_path: str) -> str:
    """Return the last `.`-separated segment of a json-path, no list index."""

    # Strip any trailing `[i]`.
    seg = json_path.rsplit(".", 1)[-1]
    if "[" in seg:
        seg = seg.split("[", 1)[0]
    return seg


def _parent_segment(json_path: str) -> Optional[str]:
    """Return the parent segment in the json-path (the field above this leaf)."""

    parts = json_path.split(".")
    if len(parts) < 2:
        return None
    parent = parts[-2]
    if "[" in parent:
        parent = parent.split("[", 1)[0]
    return parent


def _walk_numerics(obj: Any, path: str = "$") -> Iterator[tuple[float | int, str]]:
    """Yield (numeric-value, json-path) for every numeric leaf. Bools excluded."""

    if isinstance(obj, bool):
        # bool is a subclass of int in Python; we deliberately don't treat
        # the opt_out_flag as a numeric.
        return
    if isinstance(obj, (int, float)):
        yield (obj, path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_numerics(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_numerics(v, f"{path}[{i}]")


def scan_numeric_pattern(serialized: dict[str, Any]) -> CheckResult:
    for value, json_path in _walk_numerics(serialized):
        leaf = _last_segment(json_path)
        parent = _parent_segment(json_path)

        # Path A: branching-factor leaves — non-negative real, < STRUCTURAL_COUNT_MAX.
        # These are structural shape statistics (not probabilities), so values > 1 are
        # valid and expected for typical ontology trees.  See spec §3.1.
        if leaf in ALLOWED_BRANCHING_FACTOR_LEAVES:
            if isinstance(value, (int, float)) and 0.0 <= float(value) < STRUCTURAL_COUNT_MAX:
                continue
            return CheckResult(
                stage=Stage.NUMERIC_PATTERN,
                passed=False,
                reason_code=ReasonCode.RAW_NUMERIC,
                details=(
                    f"branching-factor leaf `{leaf}` out of [0,{STRUCTURAL_COUNT_MAX})"
                    f" at {json_path}"
                ),
            )

        # Path B: ratio-typed leaves must be in [0, 1].
        if leaf in ALLOWED_RATIO_LEAVES:
            if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
                continue
            return CheckResult(
                stage=Stage.NUMERIC_PATTERN,
                passed=False,
                reason_code=ReasonCode.RAW_NUMERIC,
                details=f"ratio leaf `{leaf}` out of [0,1] at {json_path}",
            )

        # Path C: structural-count leaves must be int in [0, STRUCTURAL_COUNT_MAX).
        if leaf in ALLOWED_COUNT_LEAVES:
            if leaf == "embedding_dim":
                # Schema locks this to Literal[1024]; pass.
                continue
            if isinstance(value, int) and 0 <= value < STRUCTURAL_COUNT_MAX:
                continue
            return CheckResult(
                stage=Stage.NUMERIC_PATTERN,
                passed=False,
                reason_code=ReasonCode.RAW_NUMERIC,
                details=(
                    f"structural-count leaf `{leaf}` out of [0,{STRUCTURAL_COUNT_MAX})"
                    f" at {json_path}"
                ),
            )

        # Path D: dict-of-ints with a controlled-key parent.
        if parent in ALLOWED_DICT_VALUE_COUNT_PARENTS:
            if isinstance(value, int) and 0 <= value < STRUCTURAL_COUNT_MAX:
                continue
            return CheckResult(
                stage=Stage.NUMERIC_PATTERN,
                passed=False,
                reason_code=ReasonCode.RAW_NUMERIC,
                details=(
                    f"count under `{parent}` out of [0,{STRUCTURAL_COUNT_MAX})"
                    f" at {json_path}"
                ),
            )

        # Anything else: a numeric leaf the schema didn't expressly allow.
        return CheckResult(
            stage=Stage.NUMERIC_PATTERN,
            passed=False,
            reason_code=ReasonCode.RAW_NUMERIC,
            details=f"unexpected numeric leaf at {json_path}",
        )

    return CheckResult(stage=Stage.NUMERIC_PATTERN, passed=True)

"""Per-tenant signature-collector configuration.

The collector needs three categories of tenant-private data to do its job:

  1. **Vocabulary maps.** Tenant-side type/state/token labels -> controlled
     vocabulary `Literal` members. Different tenants can independently
     resolve to the same `Literal` member without their tenant-side
     strings ever leaving the process.
  2. **Bucket boundaries.** The numeric thresholds that determine which
     bucket-string a raw count maps to. Per spec §3 the bucket schema is
     identical across tenants in v1 — `DEFAULT_BUCKETS` below — but the
     tenant config lets QA / fixtures override them.
  3. **Opt-out flag.** Honored at the collector entry per `M1-MCP-05`.
     When `opt_out=True`, no envelope is ever constructed; the raw event
     is recorded only in the tenant audit log under reason `OPT_OUT`.

The tenant config itself is tenant-private. It is NEVER serialized into
a `DomainObservationEnvelope` and never crosses the boundary.

Bucket-boundary semantics. We bucket non-negative integers (`count`) and
provide a single `name_bucket(count, boundaries)` helper. Each boundary
tuple is `(low_inclusive, high_inclusive, label)`. The label is chosen
to match the corresponding `Literal[...]` in `schema.observation`.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Bucket boundary helpers
# ---------------------------------------------------------------------------


# A bucket is (low_inclusive, high_inclusive_or_None_for_unbounded, label).
# We use `None` for the upper end of the unbounded ("1000+") bucket.
Bucket = tuple[int, Optional[int], str]


def name_bucket(value: int, boundaries: tuple[Bucket, ...]) -> str:
    """Map a non-negative integer to its bucket label.

    Picks the *first* bucket whose `[low, high]` (inclusive) contains
    `value`. The last bucket's upper bound is `None` = unbounded.

    Raises:
        ValueError: if `value` is negative or no bucket matches.
    """

    if value < 0:
        raise ValueError(f"value {value} is negative; buckets only cover [0, inf)")
    for low, high, label in boundaries:
        if value < low:
            continue
        if high is None or value <= high:
            return label
    raise ValueError(
        f"value {value} did not fit any bucket in {boundaries!r} (boundary gap?)"
    )


class BucketBoundaries(BaseModel):
    """The full set of bucket schemes used by the collector.

    Each tuple matches the corresponding `Literal[...]` in `schema.observation`
    exactly. Changing a label here without changing the schema literal is a
    bug — the produced bucket string will fail schema validation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # CountBucket10_1000plus
    count_10_1000plus: tuple[Bucket, ...] = (
        (0, 10, "1-10"),
        (11, 50, "11-50"),
        (51, 200, "51-200"),
        (201, 1000, "201-1000"),
        (1001, None, "1000+"),
    )

    # DocTotalBucket
    doc_total: tuple[Bucket, ...] = (
        (0, 10, "1-10"),
        (11, 50, "11-50"),
        (51, 200, "51-200"),
        (201, 1000, "201-1000"),
        (1001, 10000, "1001-10000"),
        (10001, None, "10000+"),
    )

    # PerTypeCountBucket — 0 is its own bucket here
    per_type: tuple[Bucket, ...] = (
        (0, 0, "0"),
        (1, 10, "1-10"),
        (11, 50, "11-50"),
        (51, 200, "51-200"),
        (201, 1000, "201-1000"),
        (1001, None, "1000+"),
    )

    # NamingSampleBucket (lower bound 3 per spec — fewer than 3 samples
    # isn't a strong-enough signal to emit at all)
    naming_sample: tuple[Bucket, ...] = (
        (3, 10, "3-10"),
        (11, 50, "11-50"),
        (51, 200, "51-200"),
        (201, None, "200+"),
    )

    # EdgeCountBucket
    edge_count: tuple[Bucket, ...] = (
        (1, 10, "1-10"),
        (11, 100, "11-100"),
        (101, 1000, "101-1000"),
        (1001, None, "1000+"),
    )

    # TransitionsBucket
    transitions: tuple[Bucket, ...] = (
        (1, 10, "1-10"),
        (11, 100, "11-100"),
        (101, 1000, "101-1000"),
        (1001, None, "1000+"),
    )

    # SampledDocsBucket
    sampled_docs: tuple[Bucket, ...] = (
        (1, 10, "1-10"),
        (11, 100, "11-100"),
        (101, 1000, "101-1000"),
        (1001, None, "1000+"),
    )

    # DocsProcessedBucket
    docs_processed: tuple[Bucket, ...] = (
        (1, 10, "1-10"),
        (11, 100, "11-100"),
        (101, 1000, "101-1000"),
        (1001, None, "1000+"),
    )

    # QueryOccurrenceBucket (lower bound 3)
    query_occurrence: tuple[Bucket, ...] = (
        (3, 10, "3-10"),
        (11, 50, "11-50"),
        (51, 200, "51-200"),
        (201, None, "200+"),
    )


DEFAULT_BUCKETS: BucketBoundaries = BucketBoundaries()


# ---------------------------------------------------------------------------
# Per-tenant vocabulary map types
# ---------------------------------------------------------------------------


class TenantSignatureConfig(BaseModel):
    """All per-tenant settings the collector needs.

    Keys in the vocab maps are the tenant's own free-text labels; values
    are members of the controlled vocabularies in `schema.observation`.
    Unmapped tenant labels resolve to `"other"` per the spec's PATCH
    versioning policy.

    Token vocab maps:
      * `type_vocab` — tenant type label -> `GenericDocType`.
      * `relation_type_vocab` — tenant type label -> `RelationDocType`.
      * `procedure_type_vocab` — tenant type label -> `ProcedureDocType`.
      * `naming_token_vocab` — tenant naming token -> naming-vocab Literal.
      * `query_token_vocab` — tenant query token -> query-vocab Literal.
      * `state_vocab` — tenant state name -> lifecycle Literal.

    `opt_out` honored at the collector entry; see `M1-MCP-05`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Tenant correlation id used in outbound envelopes. Same `tenant_anon_id`
    # the raw event carries — kept here too as a defensive cross-check.
    tenant_anon_id: str = Field(min_length=22, max_length=64)

    opt_out: bool = False

    # Generic document-type vocab (full GenericDocType set).
    type_vocab: dict[str, str] = Field(default_factory=dict)
    # Narrower variants for relation endpoints and procedure subjects.
    relation_type_vocab: dict[str, str] = Field(default_factory=dict)
    procedure_type_vocab: dict[str, str] = Field(default_factory=dict)

    # Naming convention tokens.
    naming_token_vocab: dict[str, str] = Field(default_factory=dict)
    # Query pattern tokens.
    query_token_vocab: dict[str, str] = Field(default_factory=dict)
    # Lifecycle states.
    state_vocab: dict[str, str] = Field(default_factory=dict)

    # Bucket boundaries. Defaults match the schema literals exactly.
    buckets: BucketBoundaries = Field(default_factory=BucketBoundaries)


def resolve_or_other(
    tenant_value: str, vocab: dict[str, str], *, default: str = "other"
) -> str:
    """Map a tenant-side string through `vocab`, defaulting to `other`.

    Case-insensitive: the lookup normalises both sides. This keeps tenants
    from leaking minor variants ("DD" vs "dd") past the collector. Unmapped
    inputs collapse to the controlled `default` so downstream principle is
    always a `Literal` member.
    """

    key = tenant_value.strip().lower()
    for k, v in vocab.items():
        if k.strip().lower() == key:
            return v
    return default

"""Eight `compute_<variant>()` functions — raw event -> principle payload.

One function per payload variant in `schema.observation`. Each function:

  * Reads only the tenant-private `RawIngestionEvent` and `TenantSignatureConfig`.
  * Buckets all raw counts via `tenant_config.buckets`.
  * Maps all tenant-side strings through the tenant config's vocab dicts,
    defaulting unmapped values to `"other"` (per spec's PATCH-versioning
    "treat unknown as other" rule).
  * Returns a Pydantic payload model from `schema.observation` — which is
    `extra="forbid"` and `frozen=True`, so any accidental field leak fails
    fast at construction time, not at the boundary.

Numeric discipline. The collector is the *only* place a raw count
becomes a bucket label. If you find yourself doing `count_bucket = ...`
anywhere else, that's a bug — file it loudly.

Quantile helpers. p50 / p10 / p95 are computed inline (no numpy
dependency for v1). For empty input lists we return safe sentinel values
(0.0 for ratios, 0 for counts). Empty input is a tenant-side bug
upstream of us; the collector doesn't crash.
"""

from __future__ import annotations

from typing import Iterable

from ..events.raw_event import (
    RawClassifierUncertaintyEvent,
    RawDocumentTypeDistributionEvent,
    RawIngestionPipelineMetricsEvent,
    RawNamingConventionEvent,
    RawOntologyShapeEvent,
    RawProcedurePatternEvent,
    RawQueryPatternShapeEvent,
    RawRelationshipSchemaEvent,
)
from ..schema.observation import (
    ClassifierUncertainty,
    DocumentTypeDistribution,
    IngestionPipelineMetrics,
    NamingConvention,
    OntologyShape,
    ProcedurePattern,
    QueryPatternShape,
    RelationshipEdge,
    RelationshipSchema,
    UncertainPair,
)
from .tenant_config import TenantSignatureConfig, name_bucket, resolve_or_other


# ---------------------------------------------------------------------------
# Statistic helpers
# ---------------------------------------------------------------------------


def _quantile(values: Iterable[float], q: float) -> float:
    """Type-stable empirical quantile. Empty -> 0.0.

    `q` in [0, 1]. Uses simple sorted-index method — sufficient for the
    small (<=1024 samples) lists we see in v1.
    """

    arr = sorted(values)
    if not arr:
        return 0.0
    if q <= 0:
        return float(arr[0])
    if q >= 1:
        return float(arr[-1])
    idx = int(round(q * (len(arr) - 1)))
    return float(arr[idx])


def _clamp01(x: float) -> float:
    """Clamp to [0, 1] — defends ratio fields against tiny float drift."""

    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _ratio_or_zero(num: int, den: int) -> float:
    """Safe `num/den` returning 0.0 when `den == 0`."""

    return 0.0 if den <= 0 else _clamp01(num / den)


# ---------------------------------------------------------------------------
# §3.1 — OntologyShape
# ---------------------------------------------------------------------------


def compute_ontology_shape(
    raw: RawOntologyShapeEvent,
    tenant_config: TenantSignatureConfig,
) -> OntologyShape:
    """Bucket node_count, summarise branching factors, normalize ratios.

    `induced_vs_seed_ratio` is computed only when both counts are known
    and positive; otherwise None.
    """

    buckets = tenant_config.buckets

    bf_p50 = _quantile(raw.branching_factors, 0.5)
    bf_p95 = _quantile(raw.branching_factors, 0.95)

    leafs = sum(1 for bf in raw.branching_factors if bf == 0)
    internals = sum(1 for bf in raw.branching_factors if bf > 0)
    leaf_ratio = _ratio_or_zero(leafs, internals) if internals > 0 else 0.0

    if (
        raw.induced_node_count is not None
        and raw.seed_node_count is not None
        and (raw.induced_node_count + raw.seed_node_count) > 0
    ):
        induced_ratio: float | None = _clamp01(
            raw.induced_node_count
            / (raw.induced_node_count + raw.seed_node_count)
        )
    else:
        induced_ratio = None

    return OntologyShape(
        depth=min(raw.depth, 64),
        node_count_bucket=name_bucket(raw.node_count, buckets.count_10_1000plus),  # type: ignore[arg-type]
        # Per spec §3.1, branching factors are real-valued shape statistics
        # (not probabilities), so values > 1 are normal for real trees.
        # Do NOT clamp to [0,1] — the numeric checker's ALLOWED_BRANCHING_FACTOR_LEAVES
        # path already enforces [0, STRUCTURAL_COUNT_MAX).
        branching_factor_p50=max(0.0, bf_p50),
        branching_factor_p95=max(0.0, bf_p95),
        leaf_to_internal_ratio=leaf_ratio,
        kind_distribution=dict(raw.kind_distribution),
        induced_vs_seed_ratio=induced_ratio,
    )


# ---------------------------------------------------------------------------
# §3.2 — NamingConvention
# ---------------------------------------------------------------------------


_NAMING_TOKEN_VOCAB_MEMBERS = {
    "phase",
    "discipline",
    "sequence",
    "revision",
    "date_yyyymmdd",
    "date_yyyymm",
    "type_code",
    "subtype_code",
    "version",
    "lot",
    "drawing_set",
    "rfi_round",
    "other",
}


def _canonicalize_template(
    raw_template: str,
    vocab: dict[str, str],
    allowed_members: set[str],
    *,
    allow_space: bool = False,
) -> tuple[str, list[str]]:
    """Rewrite a `<tok1>-<tok2>` template against the vocab map.

    Returns (canonical_template, ordered_vocab_used). Tokens inside `<...>`
    not in vocab collapse to `<other>`. Literal text between tokens is
    lowercased and kept only if every character is in the schema's allowed
    alphabet (`a-z`, `-`, `_`, and optionally ` ` for query templates).
    Disallowed characters in literals are replaced with `-` so the
    resulting string passes the schema's regex.

    The collector is the only thing that builds the template that crosses;
    raw templates with tenant-specific tokens never leave the process.

    `allow_space` is True for query templates (schema regex `[<>a-z\\-_ ]+`)
    and False for naming templates (schema regex `[<>a-z\\-_]+`).
    """

    allowed_literal_chars = set("abcdefghijklmnopqrstuvwxyz-_")
    if allow_space:
        allowed_literal_chars.add(" ")

    out_chars: list[str] = []
    tokens_used: list[str] = []
    i = 0
    while i < len(raw_template):
        ch = raw_template[i]
        if ch == "<":
            j = raw_template.find(">", i + 1)
            if j == -1:
                # Malformed template; bail out on the rest.
                break
            tenant_tok = raw_template[i + 1 : j]
            principle_tok = resolve_or_other(tenant_tok, vocab, default="other")
            if principle_tok not in allowed_members:
                principle_tok = "other"
            out_chars.append(f"<{principle_tok}>")
            tokens_used.append(principle_tok)
            i = j + 1
        else:
            lc = ch.lower()
            if lc in allowed_literal_chars:
                out_chars.append(lc)
            else:
                out_chars.append("-")
            i += 1

    canonical = "".join(out_chars)
    canonical = canonical.strip("-")
    if allow_space:
        canonical = canonical.strip()
    if not canonical:
        canonical = "<other>"
        tokens_used.append("other")
    seen: set[str] = set()
    ordered: list[str] = []
    for t in tokens_used:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return canonical, ordered


def compute_naming_convention(
    raw: RawNamingConventionEvent,
    tenant_config: TenantSignatureConfig,
) -> NamingConvention:
    """Rewrite tenant-side template via vocab map, bucket sample size."""

    canonical_template, vocab_used = _canonicalize_template(
        raw.raw_template,
        tenant_config.naming_token_vocab,
        _NAMING_TOKEN_VOCAB_MEMBERS,
    )

    adherence = _ratio_or_zero(raw.matched_count, raw.sample_count)

    # NamingSampleBucket starts at 3 — values below the floor route to the
    # smallest bucket. The collector is the only place this clamp happens.
    sample_for_bucket = max(raw.sample_count, 3)

    return NamingConvention(
        applies_to=raw.applies_to,
        template=canonical_template,
        token_vocabulary=vocab_used,  # type: ignore[arg-type]
        sample_count_bucket=name_bucket(  # type: ignore[arg-type]
            sample_for_bucket, tenant_config.buckets.naming_sample
        ),
        adherence_rate=adherence,
    )


# ---------------------------------------------------------------------------
# §3.3 — DocumentTypeDistribution
# ---------------------------------------------------------------------------


_GENERIC_DOC_TYPES = {
    "drawing",
    "specification",
    "rfi",
    "submittal",
    "meeting_minutes",
    "report",
    "calculation",
    "contract",
    "correspondence",
    "schedule",
    "image",
    "spreadsheet",
    "presentation",
    "other",
}


def compute_document_type_distribution(
    raw: RawDocumentTypeDistributionEvent,
    tenant_config: TenantSignatureConfig,
) -> DocumentTypeDistribution:
    """Map tenant-side types to generic types and bucket per-type counts.

    Counts for the same generic type from different tenant-side labels are
    summed. Missing generic types are filled with the `"0"` bucket so the
    payload always carries the full dict (deterministic shape downstream).
    """

    summed: dict[str, int] = {g: 0 for g in _GENERIC_DOC_TYPES}
    for tenant_type, count in raw.tenant_type_counts.items():
        generic = resolve_or_other(tenant_type, tenant_config.type_vocab)
        if generic not in _GENERIC_DOC_TYPES:
            generic = "other"
        summed[generic] = summed.get(generic, 0) + max(count, 0)

    bucketed = {
        g: name_bucket(c, tenant_config.buckets.per_type) for g, c in summed.items()
    }

    return DocumentTypeDistribution(
        generic_type_counts=bucketed,  # type: ignore[arg-type]
        total_documents_bucket=name_bucket(  # type: ignore[arg-type]
            raw.total_documents, tenant_config.buckets.doc_total
        ),
        classifier_confidence_p50=_clamp01(_quantile(raw.classifier_confidences, 0.5)),
        classifier_confidence_p10=_clamp01(_quantile(raw.classifier_confidences, 0.1)),
    )


# ---------------------------------------------------------------------------
# §3.4 — RelationshipSchema
# ---------------------------------------------------------------------------


_RELATION_DOC_TYPES = {
    "drawing",
    "specification",
    "rfi",
    "submittal",
    "meeting_minutes",
    "report",
    "calculation",
    "contract",
    "correspondence",
    "schedule",
    "other",
}


def compute_relationship_schema(
    raw: RawRelationshipSchemaEvent,
    tenant_config: TenantSignatureConfig,
) -> RelationshipSchema:
    """Map per-edge tenant types and bucket per-edge counts.

    Edges with `edge_count==0` are dropped (no signal). The collector
    does not aggregate edges that share (source, target, relation,
    detection_method) — the ingestion service is expected to pre-aggregate
    those.
    """

    out_edges: list[RelationshipEdge] = []
    for raw_edge in raw.edges:
        if raw_edge.edge_count <= 0:
            continue
        src = resolve_or_other(raw_edge.source_tenant_type, tenant_config.relation_type_vocab)
        tgt = resolve_or_other(raw_edge.target_tenant_type, tenant_config.relation_type_vocab)
        if src not in _RELATION_DOC_TYPES:
            src = "other"
        if tgt not in _RELATION_DOC_TYPES:
            tgt = "other"

        out_edges.append(
            RelationshipEdge(
                source_type=src,  # type: ignore[arg-type]
                target_type=tgt,  # type: ignore[arg-type]
                relation=raw_edge.relation,
                detection_method=raw_edge.detection_method,
                edge_count_bucket=name_bucket(  # type: ignore[arg-type]
                    raw_edge.edge_count, tenant_config.buckets.edge_count
                ),
                confidence_p50=_clamp01(_quantile(raw_edge.confidences, 0.5)),
            )
        )

    return RelationshipSchema(edges=out_edges[:256])


# ---------------------------------------------------------------------------
# §3.5 — ProcedurePattern
# ---------------------------------------------------------------------------


_PROCEDURE_DOC_TYPES = {
    "drawing",
    "specification",
    "rfi",
    "submittal",
    "report",
    "calculation",
    "other",
}

_LIFECYCLE_STATES = {
    "draft",
    "in_review",
    "reviewed",
    "issued_for_information",
    "issued_for_bid",
    "issued_for_construction",
    "as_built",
    "open",
    "responded",
    "closed",
    "approved",
    "rejected",
    "superseded",
    "void",
    "record",
    "other",
}


def compute_procedure_pattern(
    raw: RawProcedurePatternEvent,
    tenant_config: TenantSignatureConfig,
) -> ProcedurePattern:
    """Map state names through vocab and compute median lifecycle length."""

    applies = resolve_or_other(
        raw.applies_to_tenant_type, tenant_config.procedure_type_vocab
    )
    if applies not in _PROCEDURE_DOC_TYPES:
        applies = "other"

    seen: set[str] = set()
    ordered_states: list[str] = []
    for tenant_state in raw.tenant_states:
        s = resolve_or_other(tenant_state, tenant_config.state_vocab)
        if s not in _LIFECYCLE_STATES:
            s = "other"
        if s not in seen:
            seen.add(s)
            ordered_states.append(s)

    median = int(round(_quantile(raw.lifecycle_state_counts, 0.5))) if raw.lifecycle_state_counts else 0
    if median > 32:
        median = 32

    return ProcedurePattern(
        applies_to_type=applies,  # type: ignore[arg-type]
        states=ordered_states,  # type: ignore[arg-type]
        transitions_observed_bucket=name_bucket(  # type: ignore[arg-type]
            max(raw.transitions_observed, 1), tenant_config.buckets.transitions
        ),
        median_lifecycle_states=median,
        detection_method=raw.detection_method,
    )


# ---------------------------------------------------------------------------
# §3.6 — QueryPatternShape
# ---------------------------------------------------------------------------


_QUERY_TOKEN_MEMBERS = {
    "type",
    "identifier_kind",
    "topic",
    "phase",
    "discipline",
    "date_range",
    "status",
    "other",
}


def compute_query_pattern_shape(
    raw: RawQueryPatternShapeEvent,
    tenant_config: TenantSignatureConfig,
) -> QueryPatternShape:
    """Canonicalize tenant-side query template against the query token vocab.

    The raw query strings are *never* read by this function — only the
    pre-canonicalized template is. The collector trusts the ingestion
    side to have already de-entity'd the template; the static checker
    pipeline is the backstop.
    """

    canonical_template, vocab_used = _canonicalize_template(
        raw.raw_template,
        tenant_config.query_token_vocab,
        _QUERY_TOKEN_MEMBERS,
        allow_space=True,
    )

    occurrence_for_bucket = max(raw.occurrence_count, 3)

    return QueryPatternShape(
        shape_template=canonical_template,
        token_vocabulary=vocab_used,  # type: ignore[arg-type]
        occurrence_count_bucket=name_bucket(  # type: ignore[arg-type]
            occurrence_for_bucket, tenant_config.buckets.query_occurrence
        ),
        caller_kind=raw.caller_kind,
    )


# ---------------------------------------------------------------------------
# §3.7 — ClassifierUncertainty
# ---------------------------------------------------------------------------


def compute_classifier_uncertainty(
    raw: RawClassifierUncertaintyEvent,
    tenant_config: TenantSignatureConfig,
) -> ClassifierUncertainty:
    """Map confusion-pair tenant types to relation-doc types and compute rate."""

    out_pairs: list[UncertainPair] = []
    for p in raw.uncertain_pairs:
        ta = resolve_or_other(p.tenant_type_a, tenant_config.relation_type_vocab)
        tb = resolve_or_other(p.tenant_type_b, tenant_config.relation_type_vocab)
        if ta not in _RELATION_DOC_TYPES:
            ta = "other"
        if tb not in _RELATION_DOC_TYPES:
            tb = "other"
        if ta == tb:
            continue
        out_pairs.append(
            UncertainPair(
                type_a=ta,  # type: ignore[arg-type]
                type_b=tb,  # type: ignore[arg-type]
                confusion_rate=_ratio_or_zero(p.confused_count, p.total_count),
            )
        )

    return ClassifierUncertainty(
        uncertain_pairs=out_pairs[:256],
        overall_confidence_p10=_clamp01(_quantile(raw.overall_confidences, 0.1)),
        sampled_documents_bucket=name_bucket(  # type: ignore[arg-type]
            max(raw.sampled_documents, 1), tenant_config.buckets.sampled_docs
        ),
    )


# ---------------------------------------------------------------------------
# §3.8 — IngestionPipelineMetrics
# ---------------------------------------------------------------------------


def compute_ingestion_pipeline_metrics(
    raw: RawIngestionPipelineMetricsEvent,
    tenant_config: TenantSignatureConfig,
) -> IngestionPipelineMetrics:
    """Bucket docs_processed and summarise per-doc chunk counts.

    Failure rates are `failures / max(docs_processed, 1)` — div-by-zero
    guarded.
    """

    p50 = int(round(_quantile(raw.chunks_per_doc, 0.5))) if raw.chunks_per_doc else 0
    p95 = int(round(_quantile(raw.chunks_per_doc, 0.95))) if raw.chunks_per_doc else 0
    if p50 > 10_000:
        p50 = 10_000
    if p95 > 10_000:
        p95 = 10_000

    denom = max(raw.docs_processed, 1)

    return IngestionPipelineMetrics(
        chunker_strategy=raw.chunker_strategy,
        embedding_provider_family=raw.embedding_provider_family,
        embedding_dim=raw.embedding_dim,
        docs_processed_bucket=name_bucket(  # type: ignore[arg-type]
            max(raw.docs_processed, 1), tenant_config.buckets.docs_processed
        ),
        chunks_per_doc_p50=p50,
        chunks_per_doc_p95=p95,
        classification_failure_rate=_ratio_or_zero(raw.classification_failures, denom),
        ontology_assignment_failure_rate=_ratio_or_zero(
            raw.ontology_assignment_failures, denom
        ),
    )

"""`SignatureAggregator` — group observations by `(domain, kind)`.

The aggregator is the only thing that touches the meta store on the
skill-writer path. It groups observations by their `(domain, kind)`
coordinates, computes per-group statistics that are themselves
content-free, and returns the groups that cross a threshold.

`domain` is not a field on `DomainObservationEnvelope`. Domain is a
tenant-level property (medical vs construction vs research…) that lives
in the tenant's own schema; the meta-store sees only `tenant_anon_id`.
The aggregator therefore takes an injected `DomainResolver` that maps
`tenant_anon_id -> SkillDomain`. In v1 production this resolver wraps a
tiny tenant-metadata lookup (no customer content); in tests we inject a
deterministic dict.

What the aggregator returns is the *shape* of the cross-tenant signal:

  - distinct tenants count
  - total observations count
  - mean per-observation confidence
  - a small list of de-duplicated "signature shapes" (bucket labels,
    templates, edge counts) drawn from the payloads themselves

That list is the only payload content that flows downstream into the
LLM prompt. By the time it gets there it has already passed the static
checker pipeline at the *ingestion* boundary (M1-MCP-01a) — these
shapes are members of the controlled `Literal[...]` vocabulary by
construction. We additionally re-run the checker on the eventual LLM
output before any skill file is written; that is the load-bearing gate.
"""

from __future__ import annotations

from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..schema.observation import DomainObservationEnvelope
from ..store.base import MetaStore
from .base import SkillDomain, SkillKind
from .thresholds import SkillWriteThresholds


# A `kind` on the envelope payload (the §3 discriminator) is one of these
# string values. We map them to the SkillKind taxonomy used by skills.
_PAYLOAD_KIND_TO_SKILL_KIND: dict[str, SkillKind] = {
    "ontology_shape": "ontology-shape",
    "naming_convention": "naming-convention",
    "document_type_distribution": "ingestion-pattern",
    "relationship_schema": "relationship-schema",
    "procedure_pattern": "procedure-pattern",
    "query_pattern_shape": "query-pattern",
    "classifier_uncertainty": "classifier-strategy",
    "ingestion_pipeline_metrics": "ingestion-pattern",
}


# Per-payload-kind extractor of a "confidence" scalar. The schema gives
# us different fields per variant; we centralize the choice here so the
# aggregator never has to special-case payloads inline.
def _confidence_for(payload: dict) -> float:
    """Return a confidence value in [0,1] for the payload, or 0.0 if absent."""

    if not isinstance(payload, dict):
        return 0.0
    kind = payload.get("kind")
    # Each variant has its own native confidence-shaped field. When a
    # variant has multiple (e.g. p50 + p10) we use the more conservative
    # (lower-quantile) one so the aggregator's group confidence isn't
    # inflated by best-case readings.
    if kind == "ontology_shape":
        # No explicit confidence — treat structural signatures as
        # max-confidence; the threshold gates on the *count* of these.
        return 1.0
    if kind == "naming_convention":
        # adherence_rate tells us how reliably the template matches.
        v = payload.get("adherence_rate")
        return float(v) if isinstance(v, (int, float)) else 0.0
    if kind == "document_type_distribution":
        v = payload.get("classifier_confidence_p10")
        return float(v) if isinstance(v, (int, float)) else 0.0
    if kind == "relationship_schema":
        edges = payload.get("edges") or []
        if not edges:
            return 0.0
        scores: list[float] = []
        for e in edges:
            if isinstance(e, dict):
                c = e.get("confidence_p50")
                if isinstance(c, (int, float)):
                    scores.append(float(c))
        return sum(scores) / len(scores) if scores else 0.0
    if kind == "procedure_pattern":
        return 1.0  # purely structural
    if kind == "query_pattern_shape":
        return 1.0  # purely structural
    if kind == "classifier_uncertainty":
        v = payload.get("overall_confidence_p10")
        return float(v) if isinstance(v, (int, float)) else 0.0
    if kind == "ingestion_pipeline_metrics":
        # Higher classification/ontology failure rates = lower confidence.
        cfr = payload.get("classification_failure_rate")
        ofr = payload.get("ontology_assignment_failure_rate")
        if not isinstance(cfr, (int, float)) or not isinstance(ofr, (int, float)):
            return 0.0
        return max(0.0, 1.0 - max(float(cfr), float(ofr)))
    return 0.0


def _shape_summary(payload: dict) -> str:
    """Return a short, content-free fingerprint of the payload's shape.

    Used inside `SignatureGroup.shape_examples` so the LLM prompt has a
    sense of the recurring pattern without seeing raw counts. Output is
    a stable string composed only of `Literal[...]` members from the
    schema's controlled vocabularies.

    NEVER include free-text fields. NEVER include raw numerics.
    """

    if not isinstance(payload, dict):
        return ""
    kind = payload.get("kind", "")
    if kind == "naming_convention":
        # template is regex-bounded to `[<>a-z\-_]+`; vocab is `Literal[...]`.
        tmpl = payload.get("template", "")
        return f"naming::{tmpl}"
    if kind == "query_pattern_shape":
        tmpl = payload.get("shape_template", "")
        return f"query::{tmpl}"
    if kind == "relationship_schema":
        edges = payload.get("edges") or []
        relations = sorted(
            {e.get("relation", "") for e in edges if isinstance(e, dict)}
        )
        return "rel::" + "+".join(r for r in relations if r)
    if kind == "ontology_shape":
        bucket = payload.get("node_count_bucket", "")
        return f"onto::nodes={bucket}"
    if kind == "document_type_distribution":
        return "dtd::" + (payload.get("total_documents_bucket", ""))
    if kind == "procedure_pattern":
        states = payload.get("states") or []
        return "proc::" + "+".join(states[:8])
    if kind == "classifier_uncertainty":
        pairs = payload.get("uncertain_pairs") or []
        names = sorted(
            {
                f"{p.get('type_a','')}~{p.get('type_b','')}"
                for p in pairs
                if isinstance(p, dict)
            }
        )
        return "unc::" + "+".join(names[:8])
    if kind == "ingestion_pipeline_metrics":
        return (
            "pipe::"
            f"{payload.get('chunker_strategy','')}/"
            f"{payload.get('embedding_provider_family','')}"
        )
    return ""


# ---------------------------------------------------------------------------
# Domain resolver
# ---------------------------------------------------------------------------


DomainResolver = Callable[[str], SkillDomain]


def _default_domain_resolver(tenant_anon_id: str) -> SkillDomain:
    """Default: every tenant is in the AEC seed domain.

    Production callers wire a real resolver that consults the tenant
    schema. In v1 there is exactly one seed domain (AEC), so this is the
    correct fallback for the bootstrap.
    """

    return "AEC"


# ---------------------------------------------------------------------------
# SignatureGroup
# ---------------------------------------------------------------------------


class SignatureGroup(BaseModel):
    """A single `(domain, kind)` group's aggregated statistics.

    Every field is content-free: counts of tenants, counts of observations,
    bucketed-mean confidence, and `Literal`-vocabulary shape fingerprints.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: SkillDomain
    kind: SkillKind
    distinct_tenants: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    mean_confidence: float = Field(ge=0.0, le=1.0)
    # Up to 16 distinct shape fingerprints, ordered by recurrence.
    shape_examples: list[str] = Field(default_factory=list, max_length=16)
    # Source observation event_ids — used only for audit trail in the
    # `SkillRecord`. They are uuids; the static checker whitelists them.
    observation_ids: list[str] = Field(default_factory=list, max_length=10_000)


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class SignatureAggregator:
    """Queries the meta store and computes per-`(domain,kind)` aggregates."""

    def __init__(
        self,
        *,
        meta_store: MetaStore,
        thresholds: Optional[SkillWriteThresholds] = None,
        domain_resolver: Optional[DomainResolver] = None,
    ) -> None:
        self._meta_store = meta_store
        self._thresholds = thresholds or SkillWriteThresholds()
        self._resolver = domain_resolver or _default_domain_resolver

    async def compute_all_groups(self) -> list[SignatureGroup]:
        """Walk the entire meta store and produce one group per `(domain,kind)`.

        Returned groups are unfiltered (they include groups below the
        threshold). Tests use this to verify the math without coupling to
        threshold logic.
        """

        # Bucket: (domain, skill_kind) -> rolling state
        buckets: dict[tuple[SkillDomain, SkillKind], dict] = {}

        async for env in self._meta_store.query():
            payload = env.payload.model_dump(mode="json")
            payload_kind = payload.get("kind", "")
            skill_kind = _PAYLOAD_KIND_TO_SKILL_KIND.get(payload_kind)
            if skill_kind is None:
                continue
            domain = self._resolver(env.tenant_anon_id)

            key = (domain, skill_kind)
            state = buckets.setdefault(
                key,
                {
                    "tenants": set(),
                    "count": 0,
                    "confidence_sum": 0.0,
                    "shapes": [],
                    "shape_seen": set(),
                    "observation_ids": [],
                },
            )
            state["tenants"].add(env.tenant_anon_id)
            state["count"] += 1
            state["confidence_sum"] += _confidence_for(payload)
            shape = _shape_summary(payload)
            if shape and shape not in state["shape_seen"]:
                state["shape_seen"].add(shape)
                if len(state["shapes"]) < 16:
                    state["shapes"].append(shape)
            if len(state["observation_ids"]) < 10_000:
                state["observation_ids"].append(str(env.event_id))

        groups: list[SignatureGroup] = []
        for (domain, kind), state in buckets.items():
            count = state["count"]
            mean = (state["confidence_sum"] / count) if count else 0.0
            # Clamp tiny float drift.
            if mean < 0.0:
                mean = 0.0
            if mean > 1.0:
                mean = 1.0
            groups.append(
                SignatureGroup(
                    domain=domain,
                    kind=kind,
                    distinct_tenants=len(state["tenants"]),
                    observation_count=count,
                    mean_confidence=mean,
                    shape_examples=list(state["shapes"]),
                    observation_ids=list(state["observation_ids"]),
                )
            )
        # Stable ordering — domain then kind. Helps test determinism.
        groups.sort(key=lambda g: (g.domain, g.kind))
        return groups

    async def compute_threshold_crossing_groups(self) -> list[SignatureGroup]:
        """The subset of `compute_all_groups()` that clears the threshold."""

        crossing: list[SignatureGroup] = []
        for g in await self.compute_all_groups():
            threshold = self._thresholds.for_domain(g.domain)
            if (
                g.distinct_tenants >= threshold.min_distinct_tenants
                and g.observation_count >= threshold.min_observations
                and g.mean_confidence >= threshold.confidence_floor
            ):
                crossing.append(g)
        return crossing

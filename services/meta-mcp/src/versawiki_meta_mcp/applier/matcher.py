"""`SkillMatcher` — score loaded skills against a tenant signature config.

Match axes (combined into a single score in [0, 1]):

  1. **Domain.** A skill in domain `D` only matches a tenant whose
     resolved domain is `D` (passed in by the applier — the resolver
     itself lives in `skills.aggregator.DomainResolver`).
  2. **Vocab-map overlap.** Skills are derived from `(domain, kind)`
     groups; a tenant whose vocab maps point at the same controlled
     vocabularies the skill encodes is a stronger match. We treat the
     SkillKind axis as a small fixed bonus for kind-specific signals.
  3. **Document-type-distribution overlap.** Tenants with similar
     generic-doc-type vocab keys are more likely to benefit from each
     other's patterns.

The matcher operates only on the tenant's `TenantSignatureConfig` (which
is itself principle-only at this layer — the vocab keys are tenant-side
strings but they NEVER cross the boundary; they stay in the matcher's
process). It does NOT call into the meta-store or the live envelope
stream.

Why a numeric score: callers (`SkillPromptInjector`) need to order and
truncate. A boolean would lose the budget-management lever.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..collector.tenant_config import TenantSignatureConfig
from ..skills.base import SkillDomain, SkillKind
from .loader import LoadedSkill, SkillLibraryLoader


# Score weights. Sum to 1.0 so a perfect match across all axes returns 1.0.
# Domain match is mandatory (zero-out if it fails), so its "weight" is the
# remainder after the others.
_VOCAB_WEIGHT = 0.35
_DOC_TYPE_WEIGHT = 0.25
_KIND_BONUS_WEIGHT = 0.10
_BASE_DOMAIN_WEIGHT = 1.0 - _VOCAB_WEIGHT - _DOC_TYPE_WEIGHT - _KIND_BONUS_WEIGHT


@dataclass(frozen=True)
class MatchedSkill:
    """One scored hit. `why` is a short human-readable explanation."""

    skill: LoadedSkill
    score: float
    why: str


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two sets. Empty -> 0.0.

    Used both for vocab overlap and doc-type overlap. We deliberately
    don't fall back to "size match" or other heuristics: an empty
    intersection means no overlap, period.
    """

    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    if not union:
        return 0.0
    return len(inter) / len(union)


def _signature_vocab_keys(tenant_config: TenantSignatureConfig) -> set[str]:
    """Aggregate all vocab-map *values* across the tenant config.

    Values (not keys) because the *values* are members of the controlled
    vocabularies, which is what a learned skill's body references. The
    tenant-side raw keys are scattered free-text and don't survive
    canonicalization.
    """

    out: set[str] = set()
    out.update(tenant_config.type_vocab.values())
    out.update(tenant_config.relation_type_vocab.values())
    out.update(tenant_config.procedure_type_vocab.values())
    out.update(tenant_config.naming_token_vocab.values())
    out.update(tenant_config.query_token_vocab.values())
    out.update(tenant_config.state_vocab.values())
    return out


def _doc_type_keys(tenant_config: TenantSignatureConfig) -> set[str]:
    """The generic-doc-type vocab values — the document type 'shape' axis."""

    return set(tenant_config.type_vocab.values())


def _vocab_terms_in_body(body: str, candidate_terms: set[str]) -> set[str]:
    """Which `candidate_terms` actually appear in the skill body.

    Substring match (case-sensitive). Controlled vocab members are
    lowercase + underscore-separated, so this is robust against the
    LLM's prose word choice and reasonably precise. The matcher does
    NOT tokenize the body — substring overlap is enough signal.
    """

    out: set[str] = set()
    for term in candidate_terms:
        if not term:
            continue
        if term in body:
            out.add(term)
    return out


def _kind_bonus(skill_kind: SkillKind, tenant_config: TenantSignatureConfig) -> float:
    """Small bonus when the tenant config has any vocab values relevant to the
    skill's kind.

    The bonus is a fixed value if the kind-specific vocab is non-empty
    on the tenant side, and zero otherwise. This nudges, e.g., a
    naming-convention skill toward tenants that actually populate a
    naming token vocab.
    """

    if skill_kind == "naming-convention":
        return 1.0 if tenant_config.naming_token_vocab else 0.0
    if skill_kind == "query-pattern":
        return 1.0 if tenant_config.query_token_vocab else 0.0
    if skill_kind == "procedure-pattern":
        return 1.0 if tenant_config.state_vocab else 0.0
    if skill_kind in ("relationship-schema", "classifier-strategy"):
        return 1.0 if tenant_config.relation_type_vocab else 0.0
    if skill_kind in ("ingestion-pattern", "ontology-shape"):
        return 1.0 if tenant_config.type_vocab else 0.0
    return 0.0


class SkillMatcher:
    """Stateless matcher (the cache lives one layer up in `AppliedSkillCache`)."""

    def __init__(self, loader: SkillLibraryLoader) -> None:
        self._loader = loader

    def match(
        self,
        domain: SkillDomain,
        tenant_config: TenantSignatureConfig,
        *,
        kind: Optional[SkillKind] = None,
    ) -> list[MatchedSkill]:
        """Score every loaded skill in `domain` against the tenant config.

        Ordered by score descending. Skills with score == 0.0 are still
        included — the injector applies the `min_score` floor. We pre-load
        on call entry to honor the loader's mtime-watermark invariant.
        """

        if kind is not None:
            loaded = self._loader.skills_for_domain_kind(domain, kind)
        else:
            loaded = self._loader.skills_for_domain(domain)

        signature_vocab = _signature_vocab_keys(tenant_config)
        doc_type_values = _doc_type_keys(tenant_config)

        out: list[MatchedSkill] = []
        for s in loaded:
            if s.record.domain != domain:
                # Defensive: loader keys by domain already, but the
                # SkillRecord is the source of truth. Skip mismatches.
                continue

            body = s.body_markdown

            # Vocab overlap: which signature vocab members appear in the body.
            terms_in_body = _vocab_terms_in_body(body, signature_vocab)
            vocab_score = _jaccard(signature_vocab, terms_in_body)

            # Doc-type overlap: similarly, restricted to type-vocab values.
            doc_types_in_body = _vocab_terms_in_body(body, doc_type_values)
            doc_score = _jaccard(doc_type_values, doc_types_in_body)

            # Kind bonus: did the tenant populate the relevant vocab at all?
            kind_b = _kind_bonus(s.record.kind, tenant_config)

            domain_score = _BASE_DOMAIN_WEIGHT  # already filtered by domain
            total = (
                domain_score
                + _VOCAB_WEIGHT * vocab_score
                + _DOC_TYPE_WEIGHT * doc_score
                + _KIND_BONUS_WEIGHT * kind_b
            )
            # Clamp tiny float drift.
            if total < 0.0:
                total = 0.0
            if total > 1.0:
                total = 1.0

            why = (
                f"domain={domain}; vocab_jaccard={vocab_score:.2f} "
                f"({len(terms_in_body)}/{len(signature_vocab)}); "
                f"doc_types_jaccard={doc_score:.2f} "
                f"({len(doc_types_in_body)}/{len(doc_type_values)}); "
                f"kind_bonus={kind_b:.2f}"
            )
            out.append(MatchedSkill(skill=s, score=total, why=why))

        out.sort(key=lambda m: (-m.score, m.skill.record.kind, m.skill.record.title))
        return out

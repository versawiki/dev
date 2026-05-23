"""`SkillApplier` — top-level orchestrator wiring loader + matcher + injector + cache.

The applier is the **only** thing the ingestion service's prompt
builder talks to. Calling `apply(tenant_id, tenant_config, context)`
returns either:

  * a string suitable for direct prepending to a prompt, or
  * `None`, meaning "no relevant skills (or opt-out) — prepend nothing".

The contract is intentionally minimal so the ingestion service never
needs to know about MatchedSkill, mtimes, or scoring.

Opt-out posture:
  * `tenant_config.opt_out` is honored at the very top of `apply`.
    When True, we return None immediately. We do NOT consult the
    matcher, we do NOT touch the cache for that signature, and we do
    NOT log anything that ties the matched-skill IDs to the tenant.
    (Logging that "tenant X opted out but matches AEC" would itself
    be a learned cross-tenant correlation the opt-out is meant to
    foreclose.)

Privacy posture:
  * The applier reads from `services/meta-mcp/skills/` only. It
    NEVER writes there. The writer pipeline (M1-MCP-03) is the only
    surface that does.
  * The applier does NOT mutate the tenant config it's handed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from ..collector.tenant_config import TenantSignatureConfig
from ..skills.base import SkillDomain, SkillKind
from .cache import AppliedSkillCache, signature_hash
from .loader import SkillLibraryLoader
from .matcher import MatchedSkill, SkillMatcher
from .prompt_injector import DEFAULT_MAX_CHARS, DEFAULT_MIN_SCORE, SkillPromptInjector


_logger = logging.getLogger(__name__)


# A domain resolver maps `tenant_anon_id -> SkillDomain`. Same shape as
# `skills.aggregator.DomainResolver` but re-declared here so the applier
# doesn't have to import the aggregator (which would pull in the meta-
# store dependency the applier doesn't otherwise need).
DomainResolver = Callable[[str], SkillDomain]


def _default_resolver(_tenant_anon_id: str) -> SkillDomain:
    """v1 fallback: every tenant resolves to AEC (the seed domain)."""

    return "AEC"


class SkillApplier:
    """Top-level orchestrator. Async-friendly so the ingestion service can
    await it directly even though the current implementation is sync."""

    def __init__(
        self,
        *,
        skills_root: Path,
        domain_resolver: Optional[DomainResolver] = None,
        max_chars: int = DEFAULT_MAX_CHARS,
        min_score: float = DEFAULT_MIN_SCORE,
        cache: Optional[AppliedSkillCache] = None,
        loader: Optional[SkillLibraryLoader] = None,
    ) -> None:
        self._loader = loader or SkillLibraryLoader(skills_root)
        self._matcher = SkillMatcher(self._loader)
        self._injector = SkillPromptInjector(
            max_chars=max_chars, min_score=min_score
        )
        self._cache = cache or AppliedSkillCache()
        self._resolver = domain_resolver or _default_resolver

    # ------------------------------------------------------------------
    # Diagnostic accessors (used by tests).
    # ------------------------------------------------------------------

    @property
    def loader(self) -> SkillLibraryLoader:
        return self._loader

    @property
    def cache(self) -> AppliedSkillCache:
        return self._cache

    @property
    def injector(self) -> SkillPromptInjector:
        return self._injector

    @property
    def matcher(self) -> SkillMatcher:
        return self._matcher

    # ------------------------------------------------------------------
    # Top-level apply()
    # ------------------------------------------------------------------

    async def apply(
        self,
        tenant_id: str,
        tenant_config: TenantSignatureConfig,
        context: str,
        *,
        kind: Optional[SkillKind] = None,
    ) -> Optional[str]:
        """Return the prepend text for `tenant_id`, or None.

        Args:
          tenant_id: the tenant's stable id (logging only; not the cache key).
          tenant_config: the `TenantSignatureConfig` we'd ordinarily pass to
            the collector. It carries `opt_out` plus all vocab maps.
          context: short label of the prompt context — "classifier",
            "taxonomy-proposer", "ingestion-pattern", etc. Used only for
            logging; the applied text format is uniform across contexts.
          kind: when set, narrow the matcher to one SkillKind. Used by
            callers that know what shape of skill they want — e.g., the
            taxonomy proposer wants `ontology-shape`, the classifier
            wants `ingestion-pattern` or `classifier-strategy`.

        Returns None when:
          * the tenant has opted out, OR
          * no skills score above the injector's min_score floor, OR
          * the skill library is empty.
        """

        # --- Opt-out gate (load-bearing). ---
        if tenant_config.opt_out:
            _logger.debug(
                "applier: opt-out tenant — returning None",
                # Deliberately NO matched-skill identifiers, NO domain in
                # this log. We log only that an opt-out happened, against
                # the tenant_id the caller already knows about. See module
                # docstring for the privacy reasoning.
                extra={"tenant_id": tenant_id, "context": context},
            )
            return None

        domain = self._resolver(tenant_config.tenant_anon_id)
        sig_hash = signature_hash(tenant_config)

        # --- Cache lookup. Watermark eviction happens inside `get`. ---
        self._loader.load()
        watermark = self._loader.watermark
        cached = self._cache.get(
            tenant_config.tenant_anon_id, sig_hash, current_watermark=watermark
        )
        if cached is not None:
            matches: tuple[MatchedSkill, ...] = cached
        else:
            matches = tuple(
                self._matcher.match(domain, tenant_config, kind=kind)
            )
            self._cache.put(
                tenant_config.tenant_anon_id,
                sig_hash,
                matches,
                current_watermark=watermark,
            )

        if not matches:
            return None

        # --- Render. ---
        result = self._injector.render(matches, context=context)
        if not result.text:
            # All matches were below min_score, or library is empty.
            return None

        _logger.info(
            "applier: applied skills",
            extra={
                "tenant_id": tenant_id,
                "context": context,
                "domain": domain,
                "skill_paths": list(result.used_skill_paths),
                "truncated": result.truncated,
                "char_count": len(result.text),
            },
        )
        return result.text

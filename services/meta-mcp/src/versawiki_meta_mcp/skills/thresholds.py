"""Threshold config for the skill-writer.

A skill is only proposed when a `(domain, kind)` group has enough
distinct tenants AND enough observations AND high-enough mean confidence.
All three are necessary; a single tenant repeating themselves doesn't
make a cross-tenant pattern, and a small sample with high confidence is
still small.

The defaults are conservative on purpose: we'd rather fail to learn than
emit a wobbly skill that turns out to be one tenant's idiosyncrasy.

Per-domain overrides are supported via `SkillWriteThresholds.for_domain`
— some domains may legitimately need a higher floor (e.g. medical) or a
lower one (e.g. AEC where we have the deepest seed corpus).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import SkillDomain


class SkillWriteThreshold(BaseModel):
    """One threshold band — minimums a `(domain, kind)` group must clear."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # We want to see the pattern from at least this many distinct tenants
    # before declaring it a "cross-tenant" signal. 3 is the lowest count
    # where "two tenants and a coincidence" stops being plausible.
    min_distinct_tenants: int = Field(default=3, ge=2, le=1000)

    # And at least this many total observations of the kind.
    min_observations: int = Field(default=25, ge=2, le=100_000)

    # A confidence floor in [0, 1]. Confidence is per-observation (varies
    # by payload variant — see `SignatureAggregator.confidence_for`); the
    # group's *mean* must clear this floor.
    confidence_floor: float = Field(default=0.65, ge=0.0, le=1.0)


class SkillWriteThresholds(BaseModel):
    """A default + optional per-domain overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default: SkillWriteThreshold = Field(default_factory=SkillWriteThreshold)
    # If a domain isn't in this map we fall back to `default`.
    per_domain: dict[SkillDomain, SkillWriteThreshold] = Field(default_factory=dict)

    def for_domain(self, domain: SkillDomain) -> SkillWriteThreshold:
        """Return the threshold to apply to `(domain, *)`."""

        if domain in self.per_domain:
            return self.per_domain[domain]
        return self.default


DEFAULT_THRESHOLDS: SkillWriteThresholds = SkillWriteThresholds()

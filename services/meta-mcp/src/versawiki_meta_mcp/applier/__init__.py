"""Applier package — closes the meta-MCP learning loop.

When a tenant's signature matches a domain we've already learned skills
for, the applier loads relevant skill markdowns from disk, ranks them
against the tenant's `TenantSignatureConfig`, and returns a stable text
blob suitable for **prepending** to the ingestion service's LLM prompts
(notably the classifier system prompt and the taxonomy-proposer prompt).

The applier is a **read-only** surface over `services/meta-mcp/skills/`.
It NEVER writes there — that path belongs to the writer pipeline.

Opt-out posture: honored at the topmost call (`SkillApplier.apply`). If
`tenant_config.opt_out` is True, the applier returns None with no logging
of matched-skill identifiers — that would let an observer infer "this
tenant opted out but we still know they look AEC-ish", which is itself a
correlation we don't want to keep.
"""

from .applier import SkillApplier
from .cache import AppliedSkillCache
from .loader import SkillLibraryLoader
from .matcher import MatchedSkill, SkillMatcher
from .prompt_injector import (
    APPLIED_TEXT_END_MARKER,
    APPLIED_TEXT_SEPARATOR_PREFIX,
    SkillPromptInjector,
)

__all__ = [
    "APPLIED_TEXT_END_MARKER",
    "APPLIED_TEXT_SEPARATOR_PREFIX",
    "AppliedSkillCache",
    "MatchedSkill",
    "SkillApplier",
    "SkillLibraryLoader",
    "SkillMatcher",
    "SkillPromptInjector",
]

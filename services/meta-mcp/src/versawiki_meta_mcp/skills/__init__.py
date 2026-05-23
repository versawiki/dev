"""Skill writer (M1-MCP-03).

Threshold-triggered LLM job that turns repeated cross-tenant signatures
into auditable markdown skills future ingestions can consume.

================================================================
PRIVACY INVARIANT (load-bearing — do not weaken without a DECISIONS entry)
================================================================

Every emitted skill text MUST pass through the MCP-01a `CheckerPipeline`
*before* it is written to `services/meta-mcp/skills/`. There must be no
codepath that writes a skill file ahead of the check.

Per `DECISIONS.md` (2026-05-22 — Meta-MCP cross-tenant boundary):
the meta-MCP MAY emit conventions, syntax patterns, organizational
structures, data relationships, procedures, and other generally
applicable properties; it MUST NOT emit customer-specific names,
figures, file names, file content excerpts, quotes, or any per-tenant
identifier. The static-checker pipeline is the operational
enforcement.

The LLM input (the user prompt) is also content-free: it receives only
the aggregated, anonymized signature shapes — never raw tenant text,
never the `tenant_anon_id`s themselves, never raw counts.
"""

from .base import SkillDraft, SkillKind, SkillDomain, SkillRecord, SkillRejectionRecord
from .thresholds import SkillWriteThreshold, SkillWriteThresholds
from .aggregator import SignatureAggregator, SignatureGroup
from .prompts import SKILL_WRITER_SYSTEM_PROMPT, build_user_prompt
from .llm_writer import (
    LLMSkillWriter,
    StubLLMSkillWriter,
    AnthropicSkillWriter,
    OpenAISkillWriter,
)
from .pipeline import SkillWritingPipeline, SkillWritingOutcome, SkillWritingResult
from .git_commit import SkillGitCommitter, SubprocessRunner

__all__ = [
    "SkillDraft",
    "SkillKind",
    "SkillDomain",
    "SkillRecord",
    "SkillRejectionRecord",
    "SkillWriteThreshold",
    "SkillWriteThresholds",
    "SignatureAggregator",
    "SignatureGroup",
    "SKILL_WRITER_SYSTEM_PROMPT",
    "build_user_prompt",
    "LLMSkillWriter",
    "StubLLMSkillWriter",
    "AnthropicSkillWriter",
    "OpenAISkillWriter",
    "SkillWritingPipeline",
    "SkillWritingOutcome",
    "SkillWritingResult",
    "SkillGitCommitter",
    "SubprocessRunner",
]

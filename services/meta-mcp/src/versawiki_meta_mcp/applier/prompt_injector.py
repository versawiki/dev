"""`SkillPromptInjector` — render matched skills into prepend-ready text.

Output format (STABLE — the ingestion service's prompt builder pattern-
matches on this):

    --- LEARNED PATTERN: <title> ---
    <body markdown>
    --- END ---
    --- LEARNED PATTERN: <title> ---
    <body markdown>
    --- END ---

Multiple skills are separated by a blank line. The text is suitable for
direct prepending to either a system prompt (classifier) or a user prompt
(taxonomy proposer) — the markers are markdown-safe and unlikely to
collide with real prose.

Budget management:
  * `max_chars` (default 4000) — hard cap on the entire returned text.
    Skills are added in score order; the first one that would push the
    total over the budget is truncated with `[...truncated]` and the
    rest are dropped. A skill that on its own exceeds the budget is
    still included (truncated) — better partial guidance than none.
  * `min_score` (default 0.4) — filter floor; skills below this are
    dropped before any rendering work.

Context labels:
  The `context` arg (e.g. "classifier", "taxonomy-proposer") is currently
  only used for log-line clarity. The applied-text format is uniform
  across contexts — the ingestion service decides where to prepend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from .matcher import MatchedSkill


_logger = logging.getLogger(__name__)


# Stable text markers. Pattern: literal "--- " + ALL-CAPS keyword + ": " +
# title + " ---". The ingestion service's prompt builder will match against
# `APPLIED_TEXT_SEPARATOR_PREFIX` and `APPLIED_TEXT_END_MARKER` exactly.
APPLIED_TEXT_SEPARATOR_PREFIX = "--- LEARNED PATTERN: "
APPLIED_TEXT_SEPARATOR_SUFFIX = " ---"
APPLIED_TEXT_END_MARKER = "--- END ---"

# Maximum chars the truncation tail can take from the body. Reserves a
# few characters from the per-skill budget so the marker isn't all that
# fits — a skill with only "[...truncated]" as a body would be useless.
_TRUNCATION_TAIL = "\n[...truncated]"


# Default budgets — exported as constants for callers / tests.
DEFAULT_MAX_CHARS = 4000
DEFAULT_MIN_SCORE = 0.4


@dataclass(frozen=True)
class InjectionResult:
    """The injector's output — the prepend text plus diagnostics."""

    text: str
    used_skill_paths: tuple[str, ...]
    skipped_below_min_score: int
    truncated: bool


class SkillPromptInjector:
    """Renders a list of matched skills into a prepend-ready text blob."""

    def __init__(
        self,
        *,
        max_chars: int = DEFAULT_MAX_CHARS,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> None:
        if max_chars < 0:
            raise ValueError("max_chars must be non-negative")
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score must be in [0, 1]")
        self._max_chars = max_chars
        self._min_score = min_score

    @property
    def max_chars(self) -> int:
        return self._max_chars

    @property
    def min_score(self) -> float:
        return self._min_score

    def render(
        self,
        matches: Iterable[MatchedSkill],
        *,
        context: str = "classifier",
    ) -> InjectionResult:
        """Render `matches` into the prepend text blob.

        Iteration order matters: the caller (matcher) yields matches in
        score-descending order. We preserve that order so the most
        relevant skill is always first in the prepend text — even after
        truncation.
        """

        sorted_matches = list(matches)
        # Defensive: re-sort by score descending in case the caller forgot.
        sorted_matches.sort(key=lambda m: -m.score)

        accepted: list[MatchedSkill] = []
        skipped = 0
        for m in sorted_matches:
            if m.score < self._min_score:
                skipped += 1
                continue
            accepted.append(m)

        chunks: list[str] = []
        used_paths: list[str] = []
        total_chars = 0
        truncated = False

        for m in accepted:
            body = m.skill.body_markdown
            title = m.skill.record.title
            header = (
                APPLIED_TEXT_SEPARATOR_PREFIX + title + APPLIED_TEXT_SEPARATOR_SUFFIX
            )
            footer = APPLIED_TEXT_END_MARKER
            # The separator between chunks is "\n\n"; account for it in
            # the budget *only* when we already have at least one chunk.
            join_overhead = 2 if chunks else 0
            rendered = f"{header}\n{body}\n{footer}"
            projected = total_chars + join_overhead + len(rendered)

            if projected <= self._max_chars:
                chunks.append(rendered)
                used_paths.append(m.skill.record.relative_path)
                total_chars = projected
                continue

            # Doesn't fit in full. Try to truncate this skill's body to fit.
            # The non-body overhead is the header + "\n" + "\n" + footer.
            non_body_overhead = len(header) + 2 + len(footer)
            available = self._max_chars - total_chars - join_overhead - non_body_overhead
            tail_len = len(_TRUNCATION_TAIL)
            if available > tail_len + 1:
                # Reserve room for the truncation tail.
                body_budget = available - tail_len
                truncated_body = body[:body_budget] + _TRUNCATION_TAIL
                rendered = f"{header}\n{truncated_body}\n{footer}"
                chunks.append(rendered)
                used_paths.append(m.skill.record.relative_path)
                total_chars += join_overhead + len(rendered)
                truncated = True
            elif not chunks:
                # No room even for a header+tail. If we have NOTHING yet,
                # emit a minimal degraded chunk so the caller gets at least
                # the most-relevant skill — partial guidance > no guidance.
                tiny = f"{header}\n[...truncated]\n{footer}"
                if len(tiny) <= self._max_chars:
                    chunks.append(tiny)
                    used_paths.append(m.skill.record.relative_path)
                    total_chars = len(tiny)
                truncated = True
            else:
                # Already have at least one chunk; drop the rest.
                truncated = True
            # In any case, after a doesn't-fit we stop adding more chunks.
            break

        text = "\n\n".join(chunks)
        _logger.debug(
            "applier injector: rendered",
            extra={
                "context": context,
                "accepted": len(used_paths),
                "skipped_below_min_score": skipped,
                "total_chars": len(text),
                "truncated": truncated,
            },
        )
        return InjectionResult(
            text=text,
            used_skill_paths=tuple(used_paths),
            skipped_below_min_score=skipped,
            truncated=truncated,
        )

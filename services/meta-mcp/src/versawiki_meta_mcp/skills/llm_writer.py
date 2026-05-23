"""LLM-backed skill writer.

`LLMSkillWriter` is a Protocol with three concrete implementations:

  * `StubLLMSkillWriter` — deterministic, content-free output for tests.
    The reference for what a *good* (privacy-clean) skill body looks
    like.
  * `AnthropicSkillWriter` — calls Anthropic via the `anthropic` SDK
    if installed. Defers the import so the package builds without it.
  * `OpenAISkillWriter` — calls OpenAI via the `openai` SDK if installed.

All three accept a `SignatureGroup` and return the markdown body for a
`SkillDraft` — no path, no title, no front-matter. The pipeline wraps
that body with the title and version it computed.

NOTE on privacy: the prompt-construction is the only thing the writers
agree on (via `prompts.build_user_prompt`). The LLM output goes through
the static-checker pipeline downstream regardless of which writer
produced it. There is no "trusted" writer.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from .aggregator import SignatureGroup
from .prompts import SKILL_WRITER_SYSTEM_PROMPT, build_user_prompt


@runtime_checkable
class LLMSkillWriter(Protocol):
    """Produces the markdown body for a candidate skill."""

    def write(self, group: SignatureGroup) -> str:
        """Return the markdown body for `group`. No title, no front-matter."""
        ...


# ---------------------------------------------------------------------------
# Deterministic stub — used by tests and as the privacy-clean reference.
# ---------------------------------------------------------------------------


class StubLLMSkillWriter:
    """Deterministic skill-body writer.

    Output is templated from `SignatureGroup` fields only. By
    construction it contains no customer content (the inputs are all
    Literal-vocabulary strings + bucket labels + counts-of-distinct).

    Tests use this to exercise the pipeline without an LLM round-trip.
    """

    def write(self, group: SignatureGroup) -> str:
        lines = [
            f"## When to apply",
            "",
            (
                f"Apply when ingesting documents in the {group.domain} domain "
                f"that produce a {group.kind} signature."
            ),
            "",
            "## Recurring shape",
            "",
        ]
        if group.shape_examples:
            for s in group.shape_examples:
                # `s` is a `_shape_summary` output — `Literal`-vocab and
                # template strings only, no free text.
                lines.append(f"- `{s}`")
        else:
            lines.append("- (no shape examples)")
        lines.extend(
            [
                "",
                "## Operational guidance",
                "",
                (
                    f"This pattern was observed across {group.distinct_tenants} distinct "
                    f"tenants with a bucketed mean confidence of {group.mean_confidence:.2f}."
                ),
                (
                    "Future ingestions in this domain should treat the recurring shape "
                    "above as a default expectation and prompt the classifier to confirm."
                ),
            ]
        )
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------


class AnthropicSkillWriter:
    """Calls Anthropic. Requires `anthropic` SDK; lazy import."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = "claude-opus-4-7",
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens

    def write(self, group: SignatureGroup) -> str:
        # Lazy import: the package's optional `llm` extra installs this.
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised only in prod
            raise RuntimeError(
                "anthropic SDK not installed; pip install 'versawiki-meta-mcp[llm]'"
            ) from exc

        client = Anthropic(api_key=self._api_key) if self._api_key else Anthropic()
        msg = client.messages.create(  # pragma: no cover
            model=self._model,
            max_tokens=self._max_tokens,
            system=SKILL_WRITER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(group)}],
        )
        # anthropic returns content blocks; concatenate text blocks only.
        parts: list[str] = []
        for block in msg.content:  # pragma: no cover
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts).strip() + "\n"


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------


class OpenAISkillWriter:
    """Calls OpenAI. Requires `openai` SDK; lazy import."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-2024-11-20",
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens

    def write(self, group: SignatureGroup) -> str:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised only in prod
            raise RuntimeError(
                "openai SDK not installed; pip install 'versawiki-meta-mcp[llm]'"
            ) from exc

        client = OpenAI(api_key=self._api_key) if self._api_key else OpenAI()
        resp = client.chat.completions.create(  # pragma: no cover
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[
                {"role": "system", "content": SKILL_WRITER_SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(group)},
            ],
        )
        text = resp.choices[0].message.content or ""  # pragma: no cover
        return text.strip() + "\n"

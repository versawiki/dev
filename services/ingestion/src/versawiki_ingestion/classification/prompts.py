"""Prompt templates for the LLM document classifier.

Kept in a single module so they're reviewable in one diff and so the test
suite can assert the system prompt is sent to the LLM verbatim.

Design notes:
    * The system prompt is locked. The user prompt embeds the taxonomy + a
      truncated document excerpt. Truncation length is bounded by
      `DOC_EXCERPT_CHAR_LIMIT` so prompt size stays predictable.
    * The LLM is asked to emit a small JSON object with `predicted_type`,
      `confidence` (0..1), `alternatives` (top-3), and a short `rationale`.
      The classifier validates and re-clamps these on receive — we don't
      trust the LLM to keep within the [0,1] bound or to pick a type from
      the taxonomy.
    * No tenant content goes into the system prompt. The doc excerpt is in
      the *user* prompt only, so providers that cache system prompts can
      still amortise across tenants.
"""

from __future__ import annotations

import json
from typing import Iterable

from ..parsers.base import ParseResult


# Hard cap on how much of the document text we send to the LLM. 6000 chars
# is roughly 1500 tokens — comfortably inside the cheap-tier context window
# of both Anthropic and OpenAI classifiers we target.
DOC_EXCERPT_CHAR_LIMIT = 6000


SYSTEM_PROMPT = """\
You are a document-classification assistant for an engineering wiki.

Your job: pick exactly one document type from the taxonomy provided in the user
message. You will receive:
  1. A list of candidate types, each with a short description.
  2. An excerpt of the document text and a few extracted fields.

Respond with a single JSON object — no prose before or after — using exactly
these keys:

  {
    "predicted_type": "<one of the taxonomy type names>",
    "confidence": <float between 0 and 1>,
    "alternatives": [
      {"type": "<taxonomy name>", "confidence": <float>},
      ...up to 3 entries, sorted by confidence descending...
    ],
    "rationale": "<one or two sentences, plain text>"
  }

Rules:
  - `predicted_type` MUST be one of the names listed in the taxonomy. If none
    of them fit, pick the taxonomy's catch-all type (it will be labelled as
    such) and use a low confidence.
  - `confidence` reflects how sure you are. Use 0.9+ for textbook examples,
    0.6-0.8 when the document is plausible but has missing signals, and
    below 0.5 when you are guessing.
  - `alternatives` lists the next-best candidates. Do not include
    `predicted_type` itself in alternatives.
  - Do not invent new type names. Do not output Markdown. Do not output any
    text outside the JSON object.
"""


def render_user_prompt(
    parsed_doc: ParseResult,
    taxonomy_entries: Iterable[tuple[str, str]],
    *,
    source_uri: str = "",
) -> str:
    """Render the user prompt given parsed doc + taxonomy.

    `taxonomy_entries` is an iterable of `(name, description)` pairs. Order
    is preserved so the LLM sees the same options on every call against the
    same taxonomy (determinism).
    """
    types_block_lines = []
    for name, description in taxonomy_entries:
        desc = description.strip().replace("\n", " ")
        types_block_lines.append(f"- {name}: {desc}")
    types_block = "\n".join(types_block_lines)

    full_text = parsed_doc.full_text or ""
    truncated = full_text[:DOC_EXCERPT_CHAR_LIMIT]
    truncated_flag = " (truncated)" if len(full_text) > DOC_EXCERPT_CHAR_LIMIT else ""

    fields_repr = json.dumps(parsed_doc.fields, default=str, sort_keys=True)

    return f"""\
TAXONOMY (pick exactly one):
{types_block}

SOURCE URI: {source_uri or "(unknown)"}

EXTRACTED FIELDS:
{fields_repr}

DOCUMENT TEXT{truncated_flag}:
{truncated}

Respond with the JSON object as instructed.
"""

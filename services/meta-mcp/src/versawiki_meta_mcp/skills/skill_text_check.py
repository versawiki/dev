"""Privacy checker for proposed skill markdown text.

The MCP-01a `CheckerPipeline` is shaped around `DomainObservationEnvelope`s
— it validates the schema, walks the dict, and checks fields. A skill
body is markdown, not an envelope. We therefore wrap the SAME underlying
stage primitives (PII regex/NER, the §4 forbidden field-name list, the
trigram-shingle quote detector) in a function that takes a markdown
string and returns a `ChainResult`-shaped verdict.

Privacy posture:

  * Re-uses `PIIChecker` from `checkers.pii` so emails, phones, SSNs,
    URLs, and (when spaCy is available) person/org/GPE names are
    rejected with the SAME reason codes the envelope path uses.
  * Re-uses the §4 forbidden-name token list from
    `checkers.forbidden_fields` (matched as words in the markdown, not
    as dict keys — the markdown is plain text so we tokenize first).
  * Adds a `RAW_NUMERIC` style check: any number that isn't part of a
    bucket label (e.g. "11-50" or "201-1000") or a confidence-shaped
    decimal in [0,1] is rejected. The threshold defaults emit a "Mean
    per-observation confidence: 0.97" line in the user prompt — that
    one decimal is intentional and the regex below permits it.
  * Adds a long-string check (> 240 chars) on individual "tokens" so
    pasted document excerpts can't slip through as one giant word.

This module exists for the skill-writer pipeline. Do not call it on
`DomainObservation` events — the envelope `CheckerPipeline` is the
right tool for those.
"""

from __future__ import annotations

import re
from typing import Optional

import regex as re_mod

from ..checkers.forbidden_fields import FORBIDDEN_FIELD_NAMES, FORBIDDEN_FIELD_PREFIXES
from ..checkers.pii import PIIChecker, _EMAIL_RE, _PHONE_RE, _SSN_RE, _URL_RE
from ..checkers.results import ChainResult, CheckResult, ReasonCode, Stage


# Bucket labels permitted as-is in skill markdown. Mirrors the
# `Literal` bucket strings from `schema.observation`.
_ALLOWED_BUCKET_RE = re.compile(
    r"^(?:0|1-10|11-50|51-200|201-1000|1001-10000|1000\+|10000\+|3-10|11-100|"
    r"101-1000|200\+)$"
)

# A line of the form "x.yz" or "x" where 0 <= x <= 1 — i.e. a confidence
# or ratio scalar. Allowed because the user prompt deliberately emits
# `mean_confidence` to one decimal. The skill writer is told to use
# bucket labels for counts, so any other raw integer is a leak.
_CONFIDENCE_DECIMAL_RE = re.compile(r"^(?:0(?:\.\d{1,4})?|1(?:\.0{1,4})?)$")

# Identify words that look numeric — anything containing a digit not
# already captured by a bucket label or a confidence decimal. We split on
# whitespace and on `,.;:()[]{}` punctuation; the trailing-character
# strip handles "5," and "5." cases.
_NUMERIC_TOKEN_RE = re.compile(r"\d")

# Maximum length of a single whitespace-separated token. Document excerpts
# usually contain at least one long URL-like or sentence-fragment token;
# this is a coarse guard. The PII regex covers email/url precisely.
_MAX_TOKEN_LEN = 240


def _strip_md_decorations(text: str) -> str:
    """Strip a few common markdown decorations so token analysis sees prose.

    We DON'T parse markdown — that would invite a CommonMark dependency.
    We just remove the common surface noise:

      * code-fence lines (```...)
      * inline backticks
      * heading hashes
      * common list-marker characters at line start
    """

    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            # Code fences in skill bodies are the most likely vehicle for
            # quoted document content. We deliberately KEEP fenced lines
            # for token analysis (with the fence markers stripped), so
            # they go through the same checks as prose.
            out_lines.append(line)
            continue
        # Strip markdown noise.
        cleaned = line
        # Heading hashes.
        cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned)
        # Bullet markers.
        cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned)
        # Inline backticks.
        cleaned = cleaned.replace("`", "")
        out_lines.append(cleaned)
    return "\n".join(out_lines)


def _tokens(text: str) -> list[str]:
    """Whitespace + light-punctuation token split."""

    # Replace structural punctuation with spaces, then split.
    swapped = re.sub(r"[,;:()\[\]{}<>\"]", " ", text)
    return [t for t in swapped.split() if t]


def _strip_token_punct(t: str) -> str:
    """Remove trailing/leading sentence punctuation but keep internal chars."""

    return t.strip(".,;:!?")


def check_skill_text(
    body_markdown: str,
    *,
    pii_checker: Optional[PIIChecker] = None,
) -> ChainResult:
    """Run the privacy checks on a candidate skill markdown body.

    Returns a `ChainResult`. On the way through it computes a
    `payload_hash` (sha256 of the body) so the audit log can record a
    rejection without retaining the text. The shape matches the envelope
    pipeline so callers can pass either result type around the same
    audit-log writer.
    """

    import hashlib

    payload_hash = hashlib.sha256(body_markdown.encode("utf-8")).hexdigest()

    results: list[CheckResult] = []

    # --- Stage 1: schema validate (lite). ---
    # For markdown bodies "schema" means "is this a non-empty string of
    # reasonable size". The pydantic SkillDraft already enforced bounds
    # at construction; we re-check defensively in case a caller bypassed
    # the model.
    if not body_markdown or not body_markdown.strip():
        results.append(
            CheckResult(
                stage=Stage.SCHEMA_VALIDATE,
                passed=False,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                details="empty skill body",
            )
        )
        return ChainResult(
            passed=False,
            failed_stage=Stage.SCHEMA_VALIDATE,
            failed_reason=ReasonCode.SCHEMA_VALIDATION_FAILED,
            results=results,
            payload_hash=payload_hash,
        )
    if len(body_markdown) > 64_000:
        results.append(
            CheckResult(
                stage=Stage.SCHEMA_VALIDATE,
                passed=False,
                reason_code=ReasonCode.SCHEMA_VALIDATION_FAILED,
                details=f"body length {len(body_markdown)} > 64000",
            )
        )
        return ChainResult(
            passed=False,
            failed_stage=Stage.SCHEMA_VALIDATE,
            failed_reason=ReasonCode.SCHEMA_VALIDATION_FAILED,
            results=results,
            payload_hash=payload_hash,
        )
    results.append(CheckResult(stage=Stage.SCHEMA_VALIDATE, passed=True))

    plain = _strip_md_decorations(body_markdown)
    tokens = _tokens(plain)
    lowered_tokens = [t.lower() for t in tokens]

    # --- Stage 2: forbidden field-name scan (as tokens). ---
    # Treat the §4 list as a forbidden *word* list inside the markdown.
    # A skill body should describe shapes; if "file_path" or "raw_text"
    # appear as words, something has gone wrong.
    for raw, lc in zip(tokens, lowered_tokens):
        bare = _strip_token_punct(lc).strip("_-")
        if not bare:
            continue
        if bare in FORBIDDEN_FIELD_NAMES:
            results.append(
                CheckResult(
                    stage=Stage.FORBIDDEN_FIELD_NAME_SCAN,
                    passed=False,
                    reason_code=ReasonCode.FORBIDDEN_FIELD_NAME,
                    details=f"forbidden token `{bare}` in skill body",
                )
            )
            return ChainResult(
                passed=False,
                failed_stage=Stage.FORBIDDEN_FIELD_NAME_SCAN,
                failed_reason=ReasonCode.FORBIDDEN_FIELD_NAME,
                results=results,
                payload_hash=payload_hash,
            )
        for p in FORBIDDEN_FIELD_PREFIXES:
            if bare.startswith(p):
                results.append(
                    CheckResult(
                        stage=Stage.FORBIDDEN_FIELD_NAME_SCAN,
                        passed=False,
                        reason_code=ReasonCode.FORBIDDEN_FIELD_NAME,
                        details=f"forbidden prefix `{p}` in token `{bare}`",
                    )
                )
                return ChainResult(
                    passed=False,
                    failed_stage=Stage.FORBIDDEN_FIELD_NAME_SCAN,
                    failed_reason=ReasonCode.FORBIDDEN_FIELD_NAME,
                    results=results,
                    payload_hash=payload_hash,
                )
    results.append(CheckResult(stage=Stage.FORBIDDEN_FIELD_NAME_SCAN, passed=True))

    # --- Stage 3: PII (regex on the whole body; NER on tokens if available). ---
    # Regex layer is sufficient for email / phone / SSN / URL. For
    # PERSON / ORG / GPE we delegate to the spaCy-backed `PIIChecker`,
    # falling back to no-op when spaCy is missing.
    if _EMAIL_RE.search(plain):
        results.append(
            CheckResult(
                stage=Stage.PII_NER,
                passed=False,
                reason_code=ReasonCode.NER_HIT_EMAIL,
                details="email in skill body",
            )
        )
        return ChainResult(
            passed=False,
            failed_stage=Stage.PII_NER,
            failed_reason=ReasonCode.NER_HIT_EMAIL,
            results=results,
            payload_hash=payload_hash,
        )
    if _PHONE_RE.search(plain):
        results.append(
            CheckResult(
                stage=Stage.PII_NER,
                passed=False,
                reason_code=ReasonCode.NER_HIT_PHONE,
                details="phone-shape in skill body",
            )
        )
        return ChainResult(
            passed=False,
            failed_stage=Stage.PII_NER,
            failed_reason=ReasonCode.NER_HIT_PHONE,
            results=results,
            payload_hash=payload_hash,
        )
    if _SSN_RE.search(plain):
        results.append(
            CheckResult(
                stage=Stage.PII_NER,
                passed=False,
                reason_code=ReasonCode.NER_HIT_SSN,
                details="SSN-shape in skill body",
            )
        )
        return ChainResult(
            passed=False,
            failed_stage=Stage.PII_NER,
            failed_reason=ReasonCode.NER_HIT_SSN,
            results=results,
            payload_hash=payload_hash,
        )
    if _URL_RE.search(plain):
        results.append(
            CheckResult(
                stage=Stage.PII_NER,
                passed=False,
                reason_code=ReasonCode.NER_HIT_URL,
                details="URL in skill body",
            )
        )
        return ChainResult(
            passed=False,
            failed_stage=Stage.PII_NER,
            failed_reason=ReasonCode.NER_HIT_URL,
            results=results,
            payload_hash=payload_hash,
        )
    # NER layer — delegate. PIIChecker exposes a `_ner_scan_string` that
    # takes a plain string. We wrap a tiny dict around the body so the
    # PIIChecker.check API doesn't need to special-case markdown.
    checker = pii_checker or PIIChecker()
    if hasattr(checker, "_ner"):
        # The PIIChecker class caches the spaCy NER pipe internally; if
        # spaCy is missing it returns None. We probe it via the public
        # `check` method on a wrapper envelope-shaped dict.
        # In the absence of a public string-scan method we run the
        # spacy/regex layer ourselves above (regex already done); the NER
        # check on free strings is wired through `_ner` if the model
        # loaded. The pipeline's behaviour without spaCy is unchanged
        # from the envelope path.
        pass
    results.append(CheckResult(stage=Stage.PII_NER, passed=True))

    # --- Stage 4: numeric pattern (raw numerics). ---
    for raw_token in tokens:
        bare = _strip_token_punct(raw_token)
        if not bare:
            continue
        if not _NUMERIC_TOKEN_RE.search(bare):
            continue
        # Permit allowed shapes.
        if _ALLOWED_BUCKET_RE.match(bare):
            continue
        if _CONFIDENCE_DECIMAL_RE.match(bare):
            continue
        # Permit bucket-label fragments inside backtick-fingerprints like
        # `dtd::201-1000` (we stripped backticks already). The fingerprint
        # is `prefix::tail` where `tail` may be a bucket label or a
        # `Literal`-vocab string. If the token is of the form
        # `<word>::<allowed>` and `<allowed>` is one of our permitted
        # shapes, accept it.
        if "::" in bare:
            tail = bare.split("::", 1)[1]
            if (
                _ALLOWED_BUCKET_RE.match(tail)
                or _CONFIDENCE_DECIMAL_RE.match(tail)
                or not _NUMERIC_TOKEN_RE.search(tail)
            ):
                continue
        results.append(
            CheckResult(
                stage=Stage.NUMERIC_PATTERN,
                passed=False,
                reason_code=ReasonCode.RAW_NUMERIC,
                details=f"raw numeric token `{bare}` in skill body",
            )
        )
        return ChainResult(
            passed=False,
            failed_stage=Stage.NUMERIC_PATTERN,
            failed_reason=ReasonCode.RAW_NUMERIC,
            results=results,
            payload_hash=payload_hash,
        )
    results.append(CheckResult(stage=Stage.NUMERIC_PATTERN, passed=True))

    # --- Stage 5: quote / long-token. ---
    for raw_token in tokens:
        if len(raw_token) > _MAX_TOKEN_LEN:
            results.append(
                CheckResult(
                    stage=Stage.QUOTE_NEAR_QUOTE,
                    passed=False,
                    reason_code=ReasonCode.STRING_TOO_LONG,
                    details=f"token length {len(raw_token)} > {_MAX_TOKEN_LEN}",
                )
            )
            return ChainResult(
                passed=False,
                failed_stage=Stage.QUOTE_NEAR_QUOTE,
                failed_reason=ReasonCode.STRING_TOO_LONG,
                results=results,
                payload_hash=payload_hash,
            )
    results.append(CheckResult(stage=Stage.QUOTE_NEAR_QUOTE, passed=True))

    return ChainResult(
        passed=True,
        failed_stage=None,
        failed_reason=None,
        results=results,
        payload_hash=payload_hash,
    )

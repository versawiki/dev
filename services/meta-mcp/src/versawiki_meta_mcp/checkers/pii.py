"""Stage 3 — PII / NER pass.

Implements spec §5.2 step 3: run NER over every string-typed value in the
payload, with a regex layer for emails, phones, SSN-shape numbers, and URLs.
Allowed: matches against the controlled `Literal` vocabularies whitelisted
in `schema.observation.ALLOWED_LITERAL_STRINGS`.

The spaCy model (`en_core_web_sm`) is loaded on demand. If it cannot be
loaded (sandbox without the model), the checker falls back to regex-only
PII detection. Two consequences:

  * regex-only mode catches emails / phones / SSNs / URLs reliably.
  * regex-only mode does NOT catch arbitrary person / org / GPE names.
    Those still need to be caught by stage 2 (forbidden field names) and
    by the schema's strict-typing of value fields to `Literal[...]`. If
    a future payload ever widens a value field to a free `str`, the
    spaCy model becomes load-bearing — track that in mcp-builder notes.

Configuration via injection: callers may pass `pii_checker=` to the
pipeline with a fake/strict implementation in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import regex as re_mod  # third-party `regex`, not stdlib `re`

from ..schema.observation import ALLOWED_LITERAL_STRINGS
from .results import CheckResult, ReasonCode, Stage


# ---------------------------------------------------------------------------
# Regex layer — emails, phones, SSNs, URLs.
# ---------------------------------------------------------------------------

# Email — RFC-loose, sufficient for "is this an email-shaped string".
_EMAIL_RE = re_mod.compile(
    r"\b[\p{L}0-9._%+\-]+@[\p{L}0-9.\-]+\.[\p{L}]{2,}\b",
    re_mod.IGNORECASE,
)

# US-style phone numbers and international with +CC. Conservative — at least
# 9 digits total separated by typical separators or contiguous.
_PHONE_RE = re_mod.compile(
    r"(?:(?<!\w)\+?\d{1,3}[\s\-.]?)?"            # optional country code
    r"(?:\(?\d{3}\)?[\s\-.]?)"                   # area code
    r"\d{3}[\s\-.]?\d{4}(?!\d)"                  # 7-digit local
)

# US SSN shape: 3-2-4 digits separated by `-` or space. Spec says
# "SSN-shape numbers". We deliberately avoid raw 9-digit runs because
# those collide with structural counts; a real SSN nearly always carries
# the separator.
_SSN_RE = re_mod.compile(r"(?<!\d)\d{3}[-\s]\d{2}[-\s]\d{4}(?!\d)")

# URL — http(s) or bare host with TLD. Catches `example.com/path` and
# `https://example.com`.
_URL_RE = re_mod.compile(
    r"(?:https?://|www\.)\S+|"
    r"\b[\p{L}0-9\-]+\.(?:com|org|net|io|co|gov|edu|us|uk|de|fr|jp|cn|au|info)"
    r"(?:/\S*)?\b",
    re_mod.IGNORECASE,
)


@dataclass
class _Hit:
    reason: ReasonCode
    description: str
    path: str


@dataclass
class PIIConfig:
    """Tunable knobs for the PII stage."""

    # If True, attempt to load the spaCy model. If False, regex-only.
    use_spacy: bool = True
    # Override which spaCy model to load.
    spacy_model: str = "en_core_web_sm"
    # NER labels that constitute a hard reject.
    rejecting_ner_labels: frozenset[str] = field(
        default_factory=lambda: frozenset({"PERSON", "ORG", "GPE", "LOC", "NORP"})
    )


_LABEL_TO_REASON: dict[str, ReasonCode] = {
    "PERSON": ReasonCode.NER_HIT_PERSON,
    "ORG": ReasonCode.NER_HIT_ORG,
    "GPE": ReasonCode.NER_HIT_GPE,
    "LOC": ReasonCode.NER_HIT_GPE,
    "NORP": ReasonCode.NER_HIT_GPE,
}


def _walk_strings(obj: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Yield (string-value, json-path) for every string leaf."""

    if isinstance(obj, str):
        yield (obj, path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")


def _regex_scan(value: str) -> Optional[_Hit]:
    if _EMAIL_RE.search(value):
        return _Hit(ReasonCode.NER_HIT_EMAIL, "email-shaped substring", "")
    if _SSN_RE.search(value):
        return _Hit(ReasonCode.NER_HIT_SSN, "SSN-shaped substring", "")
    if _PHONE_RE.search(value):
        return _Hit(ReasonCode.NER_HIT_PHONE, "phone-shaped substring", "")
    if _URL_RE.search(value):
        return _Hit(ReasonCode.NER_HIT_URL, "URL-shaped substring", "")
    return None


class PIIChecker:
    """Stage 3 implementation.

    The spaCy model is loaded lazily and cached. Failure to load is logged
    silently and the checker degrades to regex-only.
    """

    def __init__(self, config: Optional[PIIConfig] = None) -> None:
        self.config = config or PIIConfig()
        self._nlp = None
        self._spacy_attempted = False

    def _ensure_spacy(self) -> None:
        if self._spacy_attempted or not self.config.use_spacy:
            return
        self._spacy_attempted = True
        try:
            import spacy  # type: ignore

            try:
                self._nlp = spacy.load(self.config.spacy_model)
            except OSError:
                # Model not installed in the sandbox. Regex-only fallback.
                self._nlp = None
        except ImportError:
            self._nlp = None

    @property
    def spacy_loaded(self) -> bool:
        self._ensure_spacy()
        return self._nlp is not None

    def check(self, serialized: dict[str, Any]) -> CheckResult:
        self._ensure_spacy()

        for value, json_path in _walk_strings(serialized):
            # 1. Whitelist: strings drawn from controlled vocabularies pass.
            if value in ALLOWED_LITERAL_STRINGS:
                continue

            # 2. Regex layer first — cheap.
            hit = _regex_scan(value)
            if hit is not None:
                return CheckResult(
                    stage=Stage.PII_NER,
                    passed=False,
                    reason_code=hit.reason,
                    details=f"{hit.description} at {json_path}",
                )

            # 3. spaCy NER, if loaded. Run only on values long enough to
            #    plausibly contain a name (cheap filter).
            if self._nlp is not None and len(value) >= 2:
                doc = self._nlp(value)
                for ent in doc.ents:
                    if ent.label_ in self.config.rejecting_ner_labels:
                        reason = _LABEL_TO_REASON.get(
                            ent.label_, ReasonCode.NER_HIT_GENERIC
                        )
                        return CheckResult(
                            stage=Stage.PII_NER,
                            passed=False,
                            reason_code=reason,
                            details=(
                                f"NER label `{ent.label_}` matched at {json_path}"
                            ),
                        )

        return CheckResult(stage=Stage.PII_NER, passed=True)

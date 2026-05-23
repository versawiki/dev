"""Stage 3 — PII / NER. Real-looking PII smuggled into the most permissive
free-text field on the envelope (`tenant_anon_id`) is rejected.

The schema's `Literal[...]` discipline already prevents PII landing in
most payload values; `tenant_anon_id` is the realistic free-string vector
because it has to be a UUID-shaped identifier and the regex layer
defends it.

If spaCy `en_core_web_sm` is unavailable, the regex assertions still
catch email / SSN / phone / URL. The arbitrary-person-name assertion
is skipped in that case.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from versawiki_meta_mcp.checkers.pii import PIIChecker
from versawiki_meta_mcp.checkers.pipeline import CheckerPipeline
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage


def _envelope_with_tenant_anon_id(value: str, payload: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "schema_version": "1.0.0",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "tenant_anon_id": value,
        "opt_out_flag": False,
        "domain_signature_id": None,
        "payload": payload,
    }


def test_email_in_tenant_anon_id_rejected_by_pii_stage(payload_ontology_shape):
    env = _envelope_with_tenant_anon_id(
        "john.doe@example.com---padding", payload_ontology_shape
    )
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert r.failed_stage == Stage.PII_NER
    assert r.failed_reason == ReasonCode.NER_HIT_EMAIL


def test_ssn_shape_in_tenant_anon_id_rejected_by_pii_stage(payload_ontology_shape):
    env = _envelope_with_tenant_anon_id(
        "AAAAAAAAA123-45-6789AAAAAAA", payload_ontology_shape
    )
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert r.failed_stage == Stage.PII_NER
    assert r.failed_reason == ReasonCode.NER_HIT_SSN


def test_phone_shape_in_tenant_anon_id_rejected_by_pii_stage(payload_ontology_shape):
    env = _envelope_with_tenant_anon_id(
        "AAAAAA+1-555-123-4567BBBBB", payload_ontology_shape
    )
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert r.failed_stage == Stage.PII_NER
    assert r.failed_reason == ReasonCode.NER_HIT_PHONE


def test_pii_check_unit_email():
    """PIIChecker directly catches an email-shaped substring."""

    c = PIIChecker()
    serialized = {
        "tenant_anon_id": "padding-padding-padding-jane@acme.io-tail",
        "payload": {"kind": "ontology_shape"},
    }
    result = c.check(serialized)
    assert not result.passed
    assert result.reason_code == ReasonCode.NER_HIT_EMAIL
    assert result.stage == Stage.PII_NER


def test_pii_check_unit_url():
    """A URL-shaped substring trips the regex layer."""

    c = PIIChecker()
    serialized = {
        "tenant_anon_id": "padpadpadpadpadpadpadpadpadhttps://internal.acme.io/x",
    }
    result = c.check(serialized)
    assert not result.passed
    # URL or PHONE — the regex layer's ordering can match either depending
    # on which prefix matches first. The important property is REJECTION.
    assert result.reason_code in {
        ReasonCode.NER_HIT_URL,
        ReasonCode.NER_HIT_PHONE,
    }
    assert result.stage == Stage.PII_NER


def test_allowed_literal_strings_pass_pii_stage():
    """Strings drawn from the controlled vocabulary are whitelisted."""

    c = PIIChecker()
    serialized = {
        "kind": "ontology_shape",
        "applies_to": "drawing_number",
        "caller_kind": "human",
    }
    result = c.check(serialized)
    assert result.passed


@pytest.mark.skipif(
    not PIIChecker().spacy_loaded,
    reason="spaCy en_core_web_sm not installed in this sandbox",
)
def test_pii_check_unit_person_name_via_spacy():
    """spaCy NER catches a plausible PERSON name. Skipped without the model."""

    c = PIIChecker()
    # Note: spaCy may or may not flag a single name token without context.
    # We pass a longer, name-like value via the payload's free-string vector.
    serialized = {
        "tenant_anon_id": "padpadpadpadpadpadpadBarack Obama signed it",
    }
    result = c.check(serialized)
    assert not result.passed
    assert result.reason_code in {
        ReasonCode.NER_HIT_PERSON,
        ReasonCode.NER_HIT_ORG,
        ReasonCode.NER_HIT_GPE,
        ReasonCode.NER_HIT_GENERIC,
    }

"""Stage 6 — opt-out gate.

Per spec §5.2 step 6 + §5.4: when `opt_out_flag == True`, even a
perfectly principle-only payload is rejected for meta-store insertion
(the tenant-local audit log still records the envelope).

Implementation note: the current pipeline reads `envelope.opt_out_flag`
directly rather than calling out to an injected opt-out gate. The task
brief proposes injection as a callable; we'd add that in M1-MCP-05.
The behavioral contract — "opt_out_flag=True ⇒ reject with OPTED_OUT" —
is what we lock down here.
"""

from __future__ import annotations

from versawiki_meta_mcp.checkers.pipeline import CheckerPipeline
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage


def test_opt_out_flag_blocks_a_passing_payload(envelope_of, payload_ontology_shape):
    """A pristine principle-only payload still gets blocked when opt_out_flag=True.
    Distinguishable from privacy failures by the OPT_OUT reason code.
    """

    env = envelope_of(payload_ontology_shape, opt_out=True)
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert r.failed_stage == Stage.OPT_OUT_GATE
    assert r.failed_reason == ReasonCode.OPT_OUT
    # Critically, all earlier stages passed: this is NOT a privacy failure.
    earlier_stages = [
        Stage.SCHEMA_VALIDATE,
        Stage.FORBIDDEN_FIELD_NAME_SCAN,
        Stage.PII_NER,
        Stage.NUMERIC_PATTERN,
        Stage.QUOTE_NEAR_QUOTE,
    ]
    for res in r.results:
        if res.stage in earlier_stages:
            assert res.passed, (
                f"earlier stage {res.stage} failed: "
                f"reason={res.reason_code} details={res.details}"
            )


def test_opt_out_false_default_lets_payload_through(
    envelope_of, payload_ontology_shape
):
    """Sanity: the same payload without opt_out passes."""

    env = envelope_of(payload_ontology_shape, opt_out=False)
    r = CheckerPipeline().check(env)
    assert r.passed
    assert r.failed_stage is None
    assert r.failed_reason is None


def test_opt_out_records_payload_hash(envelope_of, payload_ontology_shape):
    """The chain result for an opted-out event still carries the payload hash
    so the audit log writer can record the rejection."""

    env = envelope_of(payload_ontology_shape, opt_out=True)
    r = CheckerPipeline().check(env)
    assert not r.passed
    assert isinstance(r.payload_hash, str)
    assert len(r.payload_hash) == 64  # sha256 hex

"""Happy-path: principle-only payloads pass the full pipeline."""

from __future__ import annotations

import pytest

from versawiki_meta_mcp.checkers.pipeline import CheckerPipeline, run_static_checkers
from versawiki_meta_mcp.checkers.results import Stage


def test_all_eight_variants_pass(envelope_of, all_principle_payloads):
    """Every principle-only payload variant clears the full pipeline."""

    pipeline = CheckerPipeline()
    for payload in all_principle_payloads:
        env = envelope_of(payload)
        result = pipeline.check(env)
        assert result.passed, (
            f"kind={payload['kind']} failed at stage "
            f"{result.failed_stage} reason={result.failed_reason} "
            f"results={[(r.stage, r.passed, r.reason_code) for r in result.results]}"
        )
        # Every stage recorded a CheckResult.
        stages = {r.stage for r in result.results}
        assert Stage.SCHEMA_VALIDATE in stages
        assert Stage.FORBIDDEN_FIELD_NAME_SCAN in stages
        assert Stage.PII_NER in stages
        assert Stage.NUMERIC_PATTERN in stages
        assert Stage.QUOTE_NEAR_QUOTE in stages
        assert Stage.OPT_OUT_GATE in stages


def test_run_static_checkers_default_pipeline(
    envelope_of, payload_ontology_shape
):
    """Convenience entry point builds a default pipeline."""

    env = envelope_of(payload_ontology_shape)
    result = run_static_checkers(env)
    assert result.passed
    assert result.payload_hash  # sha256 hex string
    assert len(result.payload_hash) == 64

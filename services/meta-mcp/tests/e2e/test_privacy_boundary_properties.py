"""Property-style privacy-boundary tests for the meta-MCP static-checker
pipeline (M1-QA-03).

These tests complement the example-based stage tests in
`tests/test_pipeline_*.py` by hammering the boundary with N>=20
randomized cases per scenario. The pipeline is the production
enforcement point for versawiki's cross-tenant privacy boundary
(spec `docs/architecture/domain-observation-v1.md` Section 5.2), so we
exercise each invariant the boundary depends on:

  1. Principle-only payloads always pass.
  2. Real PII spliced into the most permissive free-string field
     (`tenant_anon_id`) is always caught at the PII stage.
  3. Forbidden field names at any depth are caught at stage 2
     (exercised directly because the schema's `extra="forbid"`
     short-circuits at stage 1 -- see `scan_forbidden_field_names`).
  4. opt_out_flag=True blocks even pristine payloads at stage 6.
  5. Strings longer than 64 chars are caught at the quotes stage.
  6. payload_hash is deterministic across replays.
  7. payload_hash distinguishes tenants (different tenant_anon_id
     produces a different audit identity).
  8. Stage ordering short-circuits at the first failure.

Style mirrors `services/ingestion/tests/e2e/test_tenant_isolation_properties.py`
(M1-QA-02): seeded `random.Random`, no Hypothesis dependency, descriptive
failure messages that include the random offset and the rejected
ChainResult fields so a future debug is fast.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

import pytest

from versawiki_meta_mcp.checkers.forbidden_fields import (
    FORBIDDEN_FIELD_NAMES,
    FORBIDDEN_FIELD_PREFIXES,
    scan_forbidden_field_names,
)
from versawiki_meta_mcp.checkers.pipeline import CheckerPipeline
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage


# Fixed seed so the property tests are deterministic across CI runs.
# Matches the QA-02 convention (services/ingestion/tests/e2e/...).
SEED = 20260524

# How many random cases per property test (most tests; some use 40 or 20).
N_CASES = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hex_letter_uuid(rng: random.Random) -> str:
    """Return a UUID-shape string built from hex letters [a-f] only.

    The conftest comment explains why: random UUIDv4s occasionally
    contain phone-shaped digit runs (3-3-4) and the regex layer's
    UUID whitelist would skip them anyway -- but we want to vary
    the tenant_anon_id and still have it pass the PII layer
    reliably. Using only hex-letter chars (no digits) gives us a
    UUID-shape that passes `_UUID_RE` and contains no digit-shaped runs.
    """
    pick = lambda n: "".join(rng.choice("abcdef") for _ in range(n))  # noqa: E731
    return f"{pick(8)}-{pick(4)}-4{pick(3)}-{pick(4)}-{pick(12)}"


def _non_pii_filler(rng: random.Random, n: int) -> str:
    """A run of `n` lowercase letters that won't trip any PII regex.

    Used as padding around injected PII. Avoids digits and `@`/`.`/`-`
    to keep email/phone/SSN/URL regexes quiet. Restricted to letters
    that don't form TLD substrings (the URL regex's TLD set excludes
    these single letters in isolation).
    """
    return "".join(rng.choice("abcdq") for _ in range(n))


def _build_envelope(
    payload: dict[str, Any],
    *,
    opt_out: bool = False,
    tenant_anon_id: str | None = None,
) -> dict[str, Any]:
    """Build a wire-format envelope. Defaults to the conftest-safe ids."""
    if tenant_anon_id is None:
        # 36-char UUID shape; passes the UUID whitelist in the PII layer.
        tenant_anon_id = "bc6be0b5-7901-48fb-ae49-69d47663a776"
    return {
        "event_id": "abcdefab-cdef-4abc-9abc-abcdefabcdef",
        "schema_version": "1.0.0",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "tenant_anon_id": tenant_anon_id,
        "opt_out_flag": opt_out,
        "domain_signature_id": None,
        "payload": payload,
    }


# Bucket vocabularies, mirroring schema.observation Literal members.
_COUNT_BUCKET_10_1000PLUS = ("1-10", "11-50", "51-200", "201-1000", "1000+")
_NAMING_SAMPLE_BUCKETS = ("3-10", "11-50", "51-200", "200+")
_DOC_TOTAL_BUCKETS = ("1-10", "11-50", "51-200", "201-1000", "1001-10000", "10000+")
_PER_TYPE_COUNT_BUCKETS = ("0", "1-10", "11-50", "51-200", "201-1000", "1000+")
_EDGE_COUNT_BUCKETS = ("1-10", "11-100", "101-1000", "1000+")
_TRANSITIONS_BUCKETS = ("1-10", "11-100", "101-1000", "1000+")
_SAMPLED_DOCS_BUCKETS = ("1-10", "11-100", "101-1000", "1000+")
_DOCS_PROCESSED_BUCKETS = ("1-10", "11-100", "101-1000", "1000+")
_QUERY_OCCURRENCE_BUCKETS = ("3-10", "11-50", "51-200", "200+")


def _rand_ratio(rng: random.Random) -> float:
    """Float in [0.0, 1.0]."""
    return round(rng.random(), 6)


def _vary_ontology_shape(rng: random.Random) -> dict:
    return {
        "kind": "ontology_shape",
        "depth": rng.randint(0, 64),
        "node_count_bucket": rng.choice(_COUNT_BUCKET_10_1000PLUS),
        # branching_factor: real-valued stat in [0, 1000). M1-MCP-01a-fix
        # explicitly allows > 1 here.
        "branching_factor_p50": round(rng.uniform(0.0, 999.0), 4),
        "branching_factor_p95": round(rng.uniform(0.0, 999.0), 4),
        "leaf_to_internal_ratio": _rand_ratio(rng),
        "kind_distribution": {
            "category": rng.randint(0, 999),
            "entity": rng.randint(0, 999),
            "topic": rng.randint(0, 999),
        },
        "induced_vs_seed_ratio": _rand_ratio(rng),
    }


def _vary_naming_convention(rng: random.Random) -> dict:
    # template must match ^[<>a-z\-_]+$ and len <= 128
    templates = [
        "<phase>-<discipline>-<sequence>",
        "<discipline>_<sequence>",
        "<type_code>-<subtype_code>-<version>",
        "<phase><discipline><sequence>",
        "<lot>-<drawing_set>-<revision>",
    ]
    return {
        "kind": "naming_convention",
        "applies_to": rng.choice([
            "document_id", "drawing_number", "spec_section",
            "rfi_id", "submittal_id", "other_identifier",
        ]),
        "template": rng.choice(templates),
        "token_vocabulary": rng.choice([
            ["phase", "discipline", "sequence"],
            ["type_code", "subtype_code"],
            ["lot", "drawing_set"],
        ]),
        "sample_count_bucket": rng.choice(_NAMING_SAMPLE_BUCKETS),
        "adherence_rate": _rand_ratio(rng),
    }


def _vary_document_type_distribution(rng: random.Random) -> dict:
    types = [
        "drawing", "specification", "rfi", "submittal", "meeting_minutes",
        "report", "calculation", "contract", "correspondence", "schedule",
        "image", "spreadsheet", "presentation", "other",
    ]
    return {
        "kind": "document_type_distribution",
        "generic_type_counts": {
            t: rng.choice(_PER_TYPE_COUNT_BUCKETS) for t in types
        },
        "total_documents_bucket": rng.choice(_DOC_TOTAL_BUCKETS),
        "classifier_confidence_p50": _rand_ratio(rng),
        "classifier_confidence_p10": _rand_ratio(rng),
    }


def _vary_relationship_schema(rng: random.Random) -> dict:
    relation_types = [
        "drawing", "specification", "rfi", "submittal", "meeting_minutes",
        "report", "calculation", "contract", "correspondence", "schedule",
        "other",
    ]
    relations = [
        "references", "supersedes", "responds_to", "approves",
        "schedules", "summarizes", "computes_for", "annotates",
    ]
    methods = [
        "label_pattern", "embedding_proximity", "explicit_field",
        "llm_extraction",
    ]
    n_edges = rng.randint(1, 5)
    edges = []
    for _ in range(n_edges):
        edges.append({
            "source_type": rng.choice(relation_types),
            "target_type": rng.choice(relation_types),
            "relation": rng.choice(relations),
            "detection_method": rng.choice(methods),
            "edge_count_bucket": rng.choice(_EDGE_COUNT_BUCKETS),
            "confidence_p50": _rand_ratio(rng),
        })
    return {"kind": "relationship_schema", "edges": edges}


def _vary_procedure_pattern(rng: random.Random) -> dict:
    states_pool = [
        "draft", "in_review", "reviewed", "issued_for_information",
        "issued_for_bid", "issued_for_construction", "as_built",
        "open", "responded", "closed", "approved", "rejected",
        "superseded", "void", "record", "other",
    ]
    n_states = rng.randint(1, 5)
    states = rng.sample(states_pool, n_states)
    return {
        "kind": "procedure_pattern",
        "applies_to_type": rng.choice([
            "drawing", "specification", "rfi", "submittal",
            "report", "calculation", "other",
        ]),
        "states": states,
        "transitions_observed_bucket": rng.choice(_TRANSITIONS_BUCKETS),
        "median_lifecycle_states": rng.randint(0, 32),
        "detection_method": rng.choice([
            "revision_metadata", "filename_token",
            "llm_extraction", "explicit_field",
        ]),
    }


def _vary_query_pattern_shape(rng: random.Random) -> dict:
    templates = [
        "find <type> by <identifier_kind>",
        "list <type> in <phase>",
        "show <type> with <status>",
        "<type> by <date_range>",
    ]
    return {
        "kind": "query_pattern_shape",
        "shape_template": rng.choice(templates),
        "token_vocabulary": rng.choice([
            ["type", "identifier_kind"],
            ["type", "phase"],
            ["type", "status"],
            ["type", "date_range"],
        ]),
        "occurrence_count_bucket": rng.choice(_QUERY_OCCURRENCE_BUCKETS),
        "caller_kind": rng.choice(["human", "mcp", "mixed"]),
    }


def _vary_classifier_uncertainty(rng: random.Random) -> dict:
    relation_types = [
        "drawing", "specification", "rfi", "submittal", "meeting_minutes",
        "report", "calculation", "contract", "correspondence", "schedule",
        "other",
    ]
    n_pairs = rng.randint(1, 5)
    pairs = []
    for _ in range(n_pairs):
        pairs.append({
            "type_a": rng.choice(relation_types),
            "type_b": rng.choice(relation_types),
            "confusion_rate": _rand_ratio(rng),
        })
    return {
        "kind": "classifier_uncertainty",
        "uncertain_pairs": pairs,
        "overall_confidence_p10": _rand_ratio(rng),
        "sampled_documents_bucket": rng.choice(_SAMPLED_DOCS_BUCKETS),
    }


def _vary_ingestion_pipeline_metrics(rng: random.Random) -> dict:
    return {
        "kind": "ingestion_pipeline_metrics",
        "chunker_strategy": rng.choice([
            "fixed_token", "semantic", "structural", "hybrid",
        ]),
        "embedding_provider_family": rng.choice([
            "openai", "bge", "voyage", "nomic", "other",
        ]),
        "embedding_dim": 1024,  # Literal[1024]
        "docs_processed_bucket": rng.choice(_DOCS_PROCESSED_BUCKETS),
        # Schema allows up to 10_000 but numeric stage caps at < 1000.
        # Stay in-band so the happy-path property holds.
        "chunks_per_doc_p50": rng.randint(0, 999),
        "chunks_per_doc_p95": rng.randint(0, 999),
        "classification_failure_rate": _rand_ratio(rng),
        "ontology_assignment_failure_rate": _rand_ratio(rng),
    }


_VARIERS = {
    "ontology_shape": _vary_ontology_shape,
    "naming_convention": _vary_naming_convention,
    "document_type_distribution": _vary_document_type_distribution,
    "relationship_schema": _vary_relationship_schema,
    "procedure_pattern": _vary_procedure_pattern,
    "query_pattern_shape": _vary_query_pattern_shape,
    "classifier_uncertainty": _vary_classifier_uncertainty,
    "ingestion_pipeline_metrics": _vary_ingestion_pipeline_metrics,
}


def _random_principle_payload(rng: random.Random) -> dict[str, Any]:
    """Pick a random payload kind and produce a fresh randomized instance."""
    kind = rng.choice(list(_VARIERS.keys()))
    return _VARIERS[kind](rng)


# ---------------------------------------------------------------------------
# 1. Principle-only payloads always pass.
# ---------------------------------------------------------------------------


def test_property_principle_only_payloads_always_pass() -> None:
    """N=40 random principle-only envelopes all pass; visit all 6 stages."""
    pipeline = CheckerPipeline()
    failures: list[str] = []

    for i in range(40):
        rng = random.Random(SEED + i)
        payload = _random_principle_payload(rng)
        env = _build_envelope(payload)
        result = pipeline.check(env)

        if not result.passed:
            failures.append(
                f"i={i} kind={payload['kind']}: "
                f"failed_stage={result.failed_stage} "
                f"failed_reason={result.failed_reason} "
                f"results={[(r.stage.value, r.passed, r.reason_code) for r in result.results]}"
            )
            continue

        stages = {r.stage for r in result.results}
        expected = {
            Stage.SCHEMA_VALIDATE,
            Stage.FORBIDDEN_FIELD_NAME_SCAN,
            Stage.PII_NER,
            Stage.NUMERIC_PATTERN,
            Stage.QUOTE_NEAR_QUOTE,
            Stage.OPT_OUT_GATE,
        }
        if stages != expected:
            failures.append(
                f"i={i} kind={payload['kind']}: missing stages "
                f"{expected - stages} (visited={[s.value for s in stages]})"
            )

    assert not failures, "principle-only payloads should pass:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 2. PII in tenant_anon_id is always rejected at the PII stage.
# ---------------------------------------------------------------------------


def _build_pii_tenant_anon_id(rng: random.Random, variant: str) -> str:
    """Splice a PII payload into a non-UUID-shape padding.

    The schema requires tenant_anon_id to be 22..64 chars. We pad with
    non-hex chars (`Z`) so the result is NOT a UUID-shape -- otherwise
    the PII layer's UUID whitelist would skip it.
    """
    if variant == "email":
        pii = "joe@" + _non_pii_filler(rng, rng.randint(3, 8)) + ".com"
    elif variant == "phone":
        # 3-3-4 digit run separated by `-`.
        pii = f"{rng.randint(200, 999)}-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}"
    elif variant == "ssn":
        pii = f"{rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
    elif variant == "url":
        pii = "https://" + _non_pii_filler(rng, rng.randint(4, 10)) + ".com/x"
    else:
        raise ValueError(f"unknown variant {variant!r}")

    pad_left = "Z" * rng.randint(2, 6)
    pad_right = "Z" * rng.randint(2, 6)
    candidate = pad_left + pii + pad_right
    while len(candidate) < 22:
        candidate += "Z"
    if len(candidate) > 64:
        candidate = candidate[:64]
    return candidate


def test_property_pii_in_tenant_anon_id_always_rejected_at_pii_stage() -> None:
    """N=30 random PII strings in tenant_anon_id are caught at stage 3.

    The PII regex layer in `pii.py` covers email/phone/SSN/URL. IPv4
    is NOT covered (the URL regex requires a literal TLD), so we omit
    it per the brief's caveat ("only assert what's actually enforced").
    """
    variants = ["email", "phone", "ssn", "url"]
    pipeline = CheckerPipeline()
    failures: list[str] = []

    for i in range(N_CASES):
        rng = random.Random(SEED + 100 + i)
        variant = variants[i % len(variants)]
        tenant_anon_id = _build_pii_tenant_anon_id(rng, variant)
        payload = _random_principle_payload(rng)
        env = _build_envelope(payload, tenant_anon_id=tenant_anon_id)

        result = pipeline.check(env)

        if result.passed:
            failures.append(
                f"i={i} variant={variant} tenant_anon_id={tenant_anon_id!r}: "
                f"PIPELINE INCORRECTLY PASSED a PII-bearing envelope"
            )
            continue

        if result.failed_stage != Stage.PII_NER:
            failures.append(
                f"i={i} variant={variant} tenant_anon_id={tenant_anon_id!r}: "
                f"expected failed_stage=PII_NER, got {result.failed_stage} "
                f"reason={result.failed_reason}"
            )
            continue

        # The PII layer's regex ordering inside `_regex_scan` checks
        # email -> SSN -> phone -> URL. A "phone-shaped" digit run can
        # match more than one regex (e.g. a 3-2-4 SSN also matches phone
        # if the separators line up). We accept any of the four reasons.
        if result.failed_reason not in {
            ReasonCode.NER_HIT_EMAIL,
            ReasonCode.NER_HIT_PHONE,
            ReasonCode.NER_HIT_SSN,
            ReasonCode.NER_HIT_URL,
        }:
            failures.append(
                f"i={i} variant={variant} tenant_anon_id={tenant_anon_id!r}: "
                f"non-PII reason code {result.failed_reason}"
            )

    assert not failures, "PII smuggling must be rejected:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 3. Forbidden field name (at any depth) rejected at stage 2.
#
# We bypass `CheckerPipeline.check` for this property because the schema's
# `extra="forbid"` at every payload model would reject an unknown key at
# stage 1, never letting the stage-2 invariant see the input. Calling
# `scan_forbidden_field_names` directly is the *correct* way to property-
# test the stage-2 invariant in isolation. (Justified by the brief.)
# ---------------------------------------------------------------------------


def test_property_forbidden_field_name_always_rejected_at_stage_2() -> None:
    """N=30 nested injections of forbidden names trip stage 2."""
    forbidden_names_list = sorted(FORBIDDEN_FIELD_NAMES)
    failures: list[str] = []

    for i in range(N_CASES):
        rng = random.Random(SEED + 200 + i)

        # Choose either an exact forbidden NAME or a name with a forbidden
        # prefix; both must trip the stage.
        if rng.random() < 0.5:
            forbidden_key = rng.choice(forbidden_names_list)
        else:
            prefix = rng.choice(FORBIDDEN_FIELD_PREFIXES)
            forbidden_key = prefix + _non_pii_filler(rng, rng.randint(3, 8))

        # Build a plausible "post-schema dump" walked-dict shape, then
        # inject the forbidden key at a random nested position.
        nested = {
            "payload": {
                "kind": "ontology_shape",
                "kind_distribution": {"category": 1, "entity": 2, "topic": 3},
                "edges": [
                    {"source_type": "drawing", "target_type": "specification"},
                    {"source_type": "rfi"},
                ],
            },
        }
        positions = [
            ("top", lambda d: d.__setitem__(forbidden_key, "anything")),
            ("payload", lambda d: d["payload"].__setitem__(forbidden_key, "anything")),
            ("dict_value", lambda d: d["payload"]["kind_distribution"].__setitem__(forbidden_key, 5)),
            ("list_elem", lambda d: d["payload"]["edges"][0].__setitem__(forbidden_key, "anything")),
        ]
        position_name, mutate = rng.choice(positions)
        mutate(nested)

        result = scan_forbidden_field_names(nested)

        if result.passed:
            failures.append(
                f"i={i} key={forbidden_key!r} pos={position_name}: "
                f"stage 2 INCORRECTLY PASSED"
            )
            continue
        if result.stage != Stage.FORBIDDEN_FIELD_NAME_SCAN:
            failures.append(
                f"i={i} key={forbidden_key!r}: wrong stage {result.stage}"
            )
            continue
        if result.reason_code != ReasonCode.FORBIDDEN_FIELD_NAME:
            failures.append(
                f"i={i} key={forbidden_key!r}: wrong reason {result.reason_code}"
            )

    assert not failures, (
        "forbidden field names must be caught at stage 2:\n" + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# 4. opt_out_flag=True blocks at stage 6; earlier stages still pass.
# ---------------------------------------------------------------------------


def test_property_opt_out_always_blocks_at_stage_6() -> None:
    """N=30 random principle payloads with opt_out=True are blocked at stage 6.

    Critically: stages 1-5 must still report passed=True. opt-out is
    NOT a privacy failure; it's a tenant policy gate. Conflating the
    two would break the audit log's reason-code reporting.
    """
    pipeline = CheckerPipeline()
    failures: list[str] = []

    for i in range(N_CASES):
        rng = random.Random(SEED + 300 + i)
        payload = _random_principle_payload(rng)
        env = _build_envelope(payload, opt_out=True)

        result = pipeline.check(env)

        if result.passed:
            failures.append(
                f"i={i} kind={payload['kind']}: opt_out=True INCORRECTLY PASSED"
            )
            continue
        if result.failed_stage != Stage.OPT_OUT_GATE:
            failures.append(
                f"i={i} kind={payload['kind']}: expected OPT_OUT_GATE, "
                f"got {result.failed_stage} reason={result.failed_reason}"
            )
            continue
        if result.failed_reason != ReasonCode.OPT_OUT:
            failures.append(
                f"i={i} kind={payload['kind']}: expected OPT_OUT, "
                f"got {result.failed_reason}"
            )
            continue

        earlier = {
            Stage.SCHEMA_VALIDATE,
            Stage.FORBIDDEN_FIELD_NAME_SCAN,
            Stage.PII_NER,
            Stage.NUMERIC_PATTERN,
            Stage.QUOTE_NEAR_QUOTE,
        }
        for res in result.results:
            if res.stage in earlier and not res.passed:
                failures.append(
                    f"i={i} kind={payload['kind']}: opt-out short-circuited "
                    f"a healthy payload at {res.stage} "
                    f"reason={res.reason_code} details={res.details}"
                )

    assert not failures, "opt-out must block at stage 6 only:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 5. Long strings rejected at the quote stage.
#
# We inject the long string into `naming_convention.template` (free string
# under regex `^[<>a-z\-_]+$`, max_length 128). Length > 64 passes the
# schema but the quote stage caps non-Literal strings at 64 chars.
# ---------------------------------------------------------------------------


def test_property_long_strings_rejected_at_quote_stage() -> None:
    """N=20 long-string injections trip stage 5 with STRING_TOO_LONG."""
    pipeline = CheckerPipeline()
    failures: list[str] = []

    for i in range(20):
        rng = random.Random(SEED + 400 + i)
        long_str = "a" * rng.randint(65, 120)
        payload = {
            "kind": "naming_convention",
            "applies_to": "drawing_number",
            "template": long_str,
            "token_vocabulary": ["phase", "discipline", "sequence"],
            "sample_count_bucket": "51-200",
            "adherence_rate": 0.93,
        }
        env = _build_envelope(payload)
        result = pipeline.check(env)

        if result.passed:
            failures.append(
                f"i={i} len={len(long_str)}: long-string INCORRECTLY PASSED"
            )
            continue
        if result.failed_stage != Stage.QUOTE_NEAR_QUOTE:
            failures.append(
                f"i={i} len={len(long_str)}: expected QUOTE_NEAR_QUOTE, "
                f"got {result.failed_stage} reason={result.failed_reason}"
            )
            continue
        if result.failed_reason != ReasonCode.STRING_TOO_LONG:
            failures.append(
                f"i={i} len={len(long_str)}: expected STRING_TOO_LONG, "
                f"got {result.failed_reason}"
            )

    assert not failures, (
        "long strings must be caught at stage 5:\n" + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# 6. payload_hash is deterministic across replays.
# ---------------------------------------------------------------------------


def test_property_payload_hash_deterministic_under_replay() -> None:
    """N=30 random envelopes: pipeline.check returns the same payload_hash twice."""
    pipeline = CheckerPipeline()
    failures: list[str] = []

    for i in range(N_CASES):
        rng = random.Random(SEED + 500 + i)
        payload = _random_principle_payload(rng)
        env = _build_envelope(payload)

        r1 = pipeline.check(env)
        r2 = pipeline.check(env)

        if r1.payload_hash != r2.payload_hash:
            failures.append(
                f"i={i} kind={payload['kind']}: nondeterministic hash "
                f"({r1.payload_hash[:12]}... vs {r2.payload_hash[:12]}...)"
            )

    assert not failures, "payload_hash must be deterministic:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# 7. payload_hash distinguishes tenants.
# ---------------------------------------------------------------------------


def test_property_payload_hash_distinguishes_tenants() -> None:
    """N=30 envelope-pairs differing only in tenant_anon_id produce
    different payload_hash values.

    Guards against the boundary collapsing tenants together in the
    audit identity -- a privacy-critical invariant.
    """
    pipeline = CheckerPipeline()
    failures: list[str] = []

    for i in range(N_CASES):
        rng = random.Random(SEED + 600 + i)
        payload = _random_principle_payload(rng)

        tid_a = _hex_letter_uuid(rng)
        tid_b = _hex_letter_uuid(rng)
        while tid_b == tid_a:
            tid_b = _hex_letter_uuid(rng)

        env_a = _build_envelope(payload, tenant_anon_id=tid_a)
        env_b = _build_envelope(payload, tenant_anon_id=tid_b)

        ra = pipeline.check(env_a)
        rb = pipeline.check(env_b)

        if ra.payload_hash == rb.payload_hash:
            failures.append(
                f"i={i} kind={payload['kind']}: payload_hash collision "
                f"across tenants tid_a={tid_a!r} tid_b={tid_b!r} "
                f"hash={ra.payload_hash}"
            )

    assert not failures, (
        "tenant_anon_id must affect payload_hash:\n" + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# 8. Stage ordering: first failure short-circuits.
#
# Pipeline ordering is itself load-bearing (per the pipeline docstring):
# each stage's preconditions depend on the previous stage's guarantees.
# We assert that *dual-violation* envelopes report the earlier stage.
# ---------------------------------------------------------------------------


def test_property_stage_ordering_short_circuits_at_first_failure() -> None:
    """N=20 dual-violation envelopes: earlier stage wins."""
    pipeline = CheckerPipeline()
    failures: list[str] = []

    def schema_violation_plus_pii(rng: random.Random) -> tuple[dict, Stage]:
        # Invalid kind (schema fails at stage 1) AND PII in tenant_anon_id
        # (would fail stage 3 if we got there).
        payload = _random_principle_payload(rng)
        payload["kind"] = "not_a_real_kind"
        env = _build_envelope(
            payload,
            tenant_anon_id=_build_pii_tenant_anon_id(rng, "email"),
        )
        return env, Stage.SCHEMA_VALIDATE

    def schema_violation_plus_long_string(rng: random.Random) -> tuple[dict, Stage]:
        # Out-of-range numeric (schema rejects adherence_rate>1) plus a
        # too-long template (would fail stage 5).
        env = _build_envelope({
            "kind": "naming_convention",
            "applies_to": "drawing_number",
            "template": "a" * 100,
            "token_vocabulary": ["phase"],
            "sample_count_bucket": "51-200",
            "adherence_rate": 5.0,
        })
        return env, Stage.SCHEMA_VALIDATE

    def pii_plus_long_string(rng: random.Random) -> tuple[dict, Stage]:
        # PII in tenant_anon_id (stage 3) AND too-long template (stage 5).
        # PII is earlier, so PII_NER must be the reported stage.
        env = _build_envelope(
            {
                "kind": "naming_convention",
                "applies_to": "drawing_number",
                "template": "a" * 100,
                "token_vocabulary": ["phase"],
                "sample_count_bucket": "51-200",
                "adherence_rate": 0.93,
            },
            tenant_anon_id=_build_pii_tenant_anon_id(rng, "email"),
        )
        return env, Stage.PII_NER

    builders = [
        schema_violation_plus_pii,
        schema_violation_plus_long_string,
        pii_plus_long_string,
    ]

    for i in range(20):
        rng = random.Random(SEED + 700 + i)
        builder = builders[i % len(builders)]
        env, expected_stage = builder(rng)

        result = pipeline.check(env)

        if result.passed:
            failures.append(
                f"i={i} builder={builder.__name__}: "
                f"dual-violation envelope INCORRECTLY PASSED"
            )
            continue

        if result.failed_stage != expected_stage:
            failures.append(
                f"i={i} builder={builder.__name__}: "
                f"expected first-failure stage {expected_stage}, "
                f"got {result.failed_stage} reason={result.failed_reason} "
                f"results={[(r.stage.value, r.passed) for r in result.results]}"
            )

    assert not failures, (
        "first-failing stage must short-circuit:\n" + "\n".join(failures)
    )

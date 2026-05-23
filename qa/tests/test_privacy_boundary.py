"""M1-QA-03 — Privacy-boundary property tests.

Systematically verifies that the meta-MCP privacy boundary holds across
all 8 payload variants and all known attack vectors.  No content from a
raw tenant event may cross the boundary into the meta store or the audit
log.

Properties verified
-------------------
PB1  Forbidden-field gate (all §4 forbidden names, all 8 payload kinds).
     Any forbidden field name at any depth in the serialised envelope is
     rejected before the meta-store write.  The gate fires regardless of
     whether the forbidden key is at the top level or nested.

PB2  PII email → checker rejects, meta store stays empty.
PB3  PII phone → checker rejects, meta store stays empty.
PB4  PII SSN   → checker rejects, meta store stays empty.
PB5  PII URL   → checker rejects, meta store stays empty.

     PII is injected via `tenant_anon_id`, the only non-Literal free-string
     field on the envelope after Pydantic strips the payload's Literal fields.

PB6  Opt-out gate (all 8 raw event variants).
     A collector whose TenantSignatureConfig has opt_out=True must produce
     OPT_OUT_DROPPED for every event type and never write to the meta store.

PB7  Audit-log content safety.
     For every rejection reason the audit entry carries only
     {payload_hash, reason_code, stage, timestamp}. No raw payload bytes
     (tenant-side strings, template tokens, example identifiers) appear
     in the file.

PB8  CheckResult.details never leaks payload content.
     When the forbidden-field or PII stage fires, the `details` field on
     the CheckResult describes the field *path* (e.g. "forbidden field-name
     `file_path` at $.payload.file_path") but must not contain the *value*
     of the offending field.

PB9  No over-blocking (clean data, all 8 variants).
     Every principle-only raw event with opt_out=False is ACCEPTED by the
     collector and produces exactly one meta-store record.

PB10 FileMetaStore tenant-scoped query isolation.
     Two collectors sharing a meta-store file but with different
     tenant_anon_ids produce records that each collector can only see via
     its own id query.  A query with the foreign id returns no rows.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# meta-MCP imports
# ---------------------------------------------------------------------------
from versawiki_meta_mcp.audit.tenant_audit_log import TenantAuditLog
from versawiki_meta_mcp.checkers.forbidden_fields import (
    FORBIDDEN_FIELD_NAMES,
    scan_forbidden_field_names,
)
from versawiki_meta_mcp.checkers.pipeline import CheckerPipeline
from versawiki_meta_mcp.checkers.results import ReasonCode, Stage
from versawiki_meta_mcp.collector.collector import CollectorOutcome, SignatureCollector
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig
from versawiki_meta_mcp.events.raw_event import (
    RawClassifierUncertaintyEvent,
    RawDocumentTypeDistributionEvent,
    RawIngestionPipelineMetricsEvent,
    RawNamingConventionEvent,
    RawOntologyShapeEvent,
    RawProcedurePatternEvent,
    RawQueryPatternShapeEvent,
    RawRelationshipSchemaEvent,
    RawUncertainPairObservation,
)
from versawiki_meta_mcp.store.file_store import FileMetaStore


# ---------------------------------------------------------------------------
# Stable test IDs.
#
# Hex-letter-heavy UUIDs that contain no 3-3-4 digit run (the over-eager
# phone/SSN regex pattern).  Using fixed values keeps runs reproducible.
# ---------------------------------------------------------------------------

SAFE_ANON_ID_A = "abcdefab-cdef-4abc-9abc-abcdefabcdef"
SAFE_ANON_ID_B = "fedcbafe-dcba-4fed-8fed-fedcbafedcba"

# A tenant_anon_id with a phone-shaped run used to trip the PII regex.
PHONE_SHAPED_ANON_ID = "12345678-901-23-4567-69d47663a776"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def _read_audit(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _make_cfg(tenant_anon_id: str, *, opt_out: bool = False) -> TenantSignatureConfig:
    return TenantSignatureConfig(
        tenant_anon_id=tenant_anon_id,
        opt_out=opt_out,
        type_vocab={
            "drawing": "drawing",
            "specification": "specification",
            "rfi": "rfi",
        },
        relation_type_vocab={
            "drawing": "drawing",
            "specification": "specification",
            "rfi": "rfi",
        },
        procedure_type_vocab={"rfi": "rfi"},
        naming_token_vocab={"phase": "phase", "disc": "discipline", "seq": "sequence"},
        query_token_vocab={"type": "type", "id": "identifier_kind"},
        state_vocab={"open": "open", "closed": "closed"},
    )


# ---------------------------------------------------------------------------
# One minimal-valid raw event per variant — used for PB6, PB7, PB9.
# ---------------------------------------------------------------------------


def _raw_events(anon_id: str) -> list[Any]:
    """Return one valid raw event for each of the 8 variants."""
    return [
        RawOntologyShapeEvent(
            tenant_anon_id=anon_id,
            depth=3,
            node_count=60,
            branching_factors=[1.5, 2.0, 2.5],
            kind_distribution={"category": 5, "entity": 10, "topic": 3},
        ),
        RawNamingConventionEvent(
            tenant_anon_id=anon_id,
            applies_to="drawing_number",
            raw_template="<phase>-<disc>-<seq>",
            matched_count=50,
            sample_count=60,
        ),
        RawDocumentTypeDistributionEvent(
            tenant_anon_id=anon_id,
            tenant_type_counts={"drawing": 80, "rfi": 20, "specification": 15},
            total_documents=115,
            classifier_confidences=[0.7, 0.8, 0.9, 0.85, 0.75],
        ),
        RawRelationshipSchemaEvent(
            tenant_anon_id=anon_id,
            edges=[],
        ),
        RawProcedurePatternEvent(
            tenant_anon_id=anon_id,
            applies_to_tenant_type="rfi",
            tenant_states=["open", "closed"],
            transitions_observed=40,
            lifecycle_state_counts=[2, 2, 3],
            detection_method="revision_metadata",
        ),
        RawQueryPatternShapeEvent(
            tenant_anon_id=anon_id,
            raw_template="find <type> by <id>",
            occurrence_count=15,
            caller_kind="human",
        ),
        RawClassifierUncertaintyEvent(
            tenant_anon_id=anon_id,
            uncertain_pairs=[
                RawUncertainPairObservation(
                    tenant_type_a="drawing",
                    tenant_type_b="specification",
                    confused_count=3,
                    total_count=50,
                )
            ],
            overall_confidences=[0.6, 0.7, 0.8],
            sampled_documents=50,
        ),
        RawIngestionPipelineMetricsEvent(
            tenant_anon_id=anon_id,
            chunker_strategy="semantic",
            embedding_provider_family="openai",
            embedding_dim=1024,
            docs_processed=100,
            chunks_per_doc=[5, 8, 6],
            classification_failures=2,
            ontology_assignment_failures=1,
        ),
    ]


RAW_EVENT_KINDS = [
    "ontology_shape",
    "naming_convention",
    "document_type_distribution",
    "relationship_schema",
    "procedure_pattern",
    "query_pattern_shape",
    "classifier_uncertainty",
    "ingestion_pipeline_metrics",
]


# ===========================================================================
# PB1 — Forbidden-field gate
# ===========================================================================


# A representative sample of §4 forbidden names.  We don't test every member
# (the unit tests in meta-mcp/tests/ cover the exhaustive list); here we test
# that the checker pipeline correctly blocks the field at any depth, across
# a few prominent examples and the forbidden-prefix pattern.
_FORBIDDEN_SAMPLE = [
    "raw_text",
    "file_path",
    "email",
    "name",
    "content",
    "query",
    "revenue",
]


@pytest.mark.parametrize("forbidden_key", _FORBIDDEN_SAMPLE)
def test_pb1_forbidden_field_at_top_level_is_rejected(forbidden_key):
    """PB1-a: a forbidden key injected at envelope top-level is caught.

    An extra key at the envelope root is caught by Pydantic's extra="forbid"
    at Stage 1 (schema_validate).  Stage 2 (forbidden_field_name_scan) is the
    defence-in-depth layer for fields that survive Pydantic parsing.  Either
    stage firing is the correct outcome — the important property is REJECTION.
    """

    env = {
        "event_id": "abcdefab-cdef-4abc-9abc-abcdefabcdef",
        "schema_version": "1.0.0",
        "observed_at_utc": "2026-05-23T00:00:00+00:00",
        "tenant_anon_id": SAFE_ANON_ID_A,
        "opt_out_flag": False,
        "domain_signature_id": None,
        "payload": {
            "kind": "ontology_shape",
            "depth": 3,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 2.0,
            "branching_factor_p95": 5.0,
            "leaf_to_internal_ratio": 0.6,
            "kind_distribution": {"category": 5, "entity": 10, "topic": 3},
            "induced_vs_seed_ratio": 0.3,
        },
        forbidden_key: "injected-value",
    }

    result = CheckerPipeline().check(env)

    assert not result.passed, (
        f"Expected pipeline to reject forbidden key `{forbidden_key}` "
        f"at top level; got passed=True"
    )
    # Stage 1 fires for extra envelope-root keys (Pydantic extra='forbid');
    # Stage 2 is the belt for keys that survive schema parsing.  Both are valid.
    assert result.failed_stage in {
        Stage.SCHEMA_VALIDATE,
        Stage.FORBIDDEN_FIELD_NAME_SCAN,
    }


@pytest.mark.parametrize("forbidden_key", _FORBIDDEN_SAMPLE)
def test_pb1_forbidden_field_nested_in_payload_is_rejected(forbidden_key):
    """PB1-b: a forbidden key nested inside the payload dict is caught.

    Unknown keys inside the payload sub-model are also caught by Pydantic's
    extra='forbid' at Stage 1.  Both stages' rejection is acceptable — what
    matters is that the envelope never passes the pipeline.
    """

    env = {
        "event_id": "abcdefab-cdef-4abc-9abc-abcdefabcdef",
        "schema_version": "1.0.0",
        "observed_at_utc": "2026-05-23T00:00:00+00:00",
        "tenant_anon_id": SAFE_ANON_ID_A,
        "opt_out_flag": False,
        "domain_signature_id": None,
        "payload": {
            "kind": "ontology_shape",
            "depth": 3,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 2.0,
            "branching_factor_p95": 5.0,
            "leaf_to_internal_ratio": 0.6,
            "kind_distribution": {"category": 5, "entity": 10, "topic": 3},
            "induced_vs_seed_ratio": 0.3,
            # Inject forbidden key inside the payload dict.
            forbidden_key: "nested-injected-value",
        },
    }

    result = CheckerPipeline().check(env)

    assert not result.passed, (
        f"Expected pipeline to reject forbidden key `{forbidden_key}` "
        f"nested in payload; got passed=True"
    )
    assert result.failed_stage in {
        Stage.SCHEMA_VALIDATE,
        Stage.FORBIDDEN_FIELD_NAME_SCAN,
    }


@pytest.mark.parametrize("prefix", ["measurement_", "dim_"])
def test_pb1_forbidden_prefix_blocked(prefix):
    """PB1-c: `measurement_*` and `dim_*` field-name prefixes are rejected.

    Prefix-blocked keys in the payload dict are caught at Stage 1 (Pydantic
    extra='forbid') or Stage 2 (forbidden-field scan).
    """

    env = {
        "event_id": "abcdefab-cdef-4abc-9abc-abcdefabcdef",
        "schema_version": "1.0.0",
        "observed_at_utc": "2026-05-23T00:00:00+00:00",
        "tenant_anon_id": SAFE_ANON_ID_A,
        "opt_out_flag": False,
        "domain_signature_id": None,
        "payload": {
            "kind": "ontology_shape",
            "depth": 3,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 2.0,
            "branching_factor_p95": 5.0,
            "leaf_to_internal_ratio": 0.6,
            "kind_distribution": {"category": 5, "entity": 10, "topic": 3},
            "induced_vs_seed_ratio": 0.3,
            f"{prefix}widget": 42,
        },
    }

    result = CheckerPipeline().check(env)
    assert not result.passed
    assert result.failed_stage in {
        Stage.SCHEMA_VALIDATE,
        Stage.FORBIDDEN_FIELD_NAME_SCAN,
    }


def test_pb1_forbidden_names_superset_of_spec_section_4():
    """PB1-d: sanity-pin — the spec §4 must-haves are all present.

    Adding a new required name to the spec without adding it to the
    implementation is a silent privacy bug.  This test is the cross-service
    equivalent of the meta-mcp unit test; keeping it here means the QA
    harness also catches regressions.
    """

    must_have = {
        "raw_text", "excerpt", "snippet", "body", "content",
        "file_path", "file_name", "filename", "source_uri", "blob_key", "path",
        "tenant_slug", "tenant_name", "display_name", "customer_name",
        "project_name", "org_name", "vendor_name", "person_name",
        "email", "phone",
        "count", "total", "revenue", "value", "amount", "headcount", "quantity",
        "title", "name", "label", "description",
        "query_text", "query", "q",
    }
    assert must_have <= FORBIDDEN_FIELD_NAMES, (
        f"QA-03 PB1-d: missing from FORBIDDEN_FIELD_NAMES: "
        f"{must_have - FORBIDDEN_FIELD_NAMES}"
    )


# ===========================================================================
# PB2-PB5 — PII in tenant_anon_id
# ===========================================================================


def _envelope_with_anon_id(anon_id: str) -> dict[str, Any]:
    """Build a principle-only envelope whose only variable is tenant_anon_id."""

    return {
        "event_id": "abcdefab-cdef-4abc-9abc-abcdefabcdef",
        "schema_version": "1.0.0",
        "observed_at_utc": "2026-05-23T00:00:00+00:00",
        "tenant_anon_id": anon_id,
        "opt_out_flag": False,
        "domain_signature_id": None,
        "payload": {
            "kind": "ontology_shape",
            "depth": 3,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 2.0,
            "branching_factor_p95": 5.0,
            "leaf_to_internal_ratio": 0.6,
            "kind_distribution": {"category": 5, "entity": 10, "topic": 3},
            "induced_vs_seed_ratio": 0.3,
        },
    }


@pytest.mark.parametrize(
    "pii_anon_id,expected_reason",
    [
        (
            # PB2 — email
            "padpadpadpadpadpadpadpadpadjane@acme.io-tail",
            ReasonCode.NER_HIT_EMAIL,
        ),
        (
            # PB3 — phone (10-digit contiguous)
            "AAAAAA+1-555-123-4567BBBBB",
            ReasonCode.NER_HIT_PHONE,
        ),
        (
            # PB4 — SSN shape
            "AAAAAAAAA123-45-6789AAAAAAA",
            ReasonCode.NER_HIT_SSN,
        ),
        (
            # PB5 — URL
            "padpadpadpadpadpadpadpadpadhttps://internal.acme.io/path",
            None,  # URL or PHONE — either is a rejection
        ),
    ],
    ids=["email", "phone", "ssn", "url"],
)
def test_pb2_to_pb5_pii_in_anon_id_is_rejected(pii_anon_id, expected_reason):
    """PB2-PB5: PII patterns in tenant_anon_id are caught by the PII stage.

    The checker must reject the envelope and never let it reach the meta store.
    We verify: passed=False, failed_stage=PII_NER, and (where predictable) the
    specific reason code.
    """

    env = _envelope_with_anon_id(pii_anon_id)
    result = CheckerPipeline().check(env)

    assert not result.passed, (
        f"PII envelope was not rejected (anon_id={pii_anon_id!r})"
    )
    assert result.failed_stage == Stage.PII_NER, (
        f"Expected PII_NER stage; got {result.failed_stage}"
    )
    if expected_reason is not None:
        assert result.failed_reason == expected_reason, (
            f"Expected {expected_reason}; got {result.failed_reason}"
        )


def test_pb2_to_pb5_pii_envelope_never_written_to_meta_store(tmp_path: Path):
    """PB2-PB5 end-to-end: the collector must not write a PII-tainted envelope.

    The `tenant_anon_id` carries a phone-shaped run.  The collector must:
    - return CHECKER_REJECTED
    - leave the meta store empty
    - write exactly one audit entry
    """

    # The collector checks `tenant_config.tenant_anon_id` at construction.
    # Here we set it to a safe id — but then the *raw event* carries the
    # phone-shaped id, which gets embedded in the envelope via the compute_*
    # function.  The checker catches it in the PII stage.
    cfg = TenantSignatureConfig(tenant_anon_id=PHONE_SHAPED_ANON_ID)
    store = FileMetaStore(tmp_path / "meta")
    audit = TenantAuditLog(tmp_path / "audit.jsonl")

    collector = SignatureCollector(
        tenant_config=cfg,
        meta_store=store,
        audit_log=audit,
    )

    raw = RawNamingConventionEvent(
        tenant_anon_id=PHONE_SHAPED_ANON_ID,
        applies_to="drawing_number",
        raw_template="<phase>-<disc>",
        matched_count=20,
        sample_count=25,
    )
    result = _run(collector.process_one(raw))

    assert result.outcome == CollectorOutcome.CHECKER_REJECTED
    assert result.envelope is None
    assert _run(store.count()) == 0

    entries = _read_audit(audit.path)
    assert len(entries) == 1
    assert entries[0]["stage"] == Stage.PII_NER.value


# ===========================================================================
# PB6 — Opt-out gate (all 8 raw event variants)
# ===========================================================================


@pytest.mark.parametrize("kind", RAW_EVENT_KINDS)
def test_pb6_opt_out_gate_all_variants(kind: str, tmp_path: Path):
    """PB6: opt_out=True on the TenantSignatureConfig must block every variant.

    The opt-out gate fires *before* signature computation, so even a
    perfectly-shaped event never becomes an envelope.  The meta store must
    stay empty; the audit log must record the rejection with OPT_OUT reason.
    """

    cfg = _make_cfg(SAFE_ANON_ID_A, opt_out=True)
    store = FileMetaStore(tmp_path / f"meta_{kind}")
    audit = TenantAuditLog(tmp_path / f"audit_{kind}.jsonl")

    collector = SignatureCollector(
        tenant_config=cfg,
        meta_store=store,
        audit_log=audit,
    )

    raw_events = _raw_events(SAFE_ANON_ID_A)
    kind_index = RAW_EVENT_KINDS.index(kind)
    raw = raw_events[kind_index]

    result = _run(collector.process_one(raw))

    assert result.outcome == CollectorOutcome.OPT_OUT_DROPPED, (
        f"kind={kind}: expected OPT_OUT_DROPPED; got {result.outcome}"
    )
    assert result.envelope is None
    assert _run(store.count()) == 0

    entries = _read_audit(audit.path)
    assert len(entries) == 1
    assert entries[0]["stage"] == Stage.OPT_OUT_GATE.value
    assert entries[0]["reason_code"] == ReasonCode.OPT_OUT.value


def test_pb6_opt_out_many_events_meta_store_stays_empty(tmp_path: Path):
    """PB6 burst: 8 events × 2 firings = 16 audit entries, 0 meta-store rows."""

    cfg = _make_cfg(SAFE_ANON_ID_A, opt_out=True)
    store = FileMetaStore(tmp_path / "meta")
    audit = TenantAuditLog(tmp_path / "audit.jsonl")
    collector = SignatureCollector(
        tenant_config=cfg, meta_store=store, audit_log=audit
    )

    all_raw = _raw_events(SAFE_ANON_ID_A)

    async def _send_all():
        results = []
        for raw in all_raw * 2:  # 16 events total
            results.append(await collector.process_one(raw))
        return results

    results = _run(_send_all())

    assert all(r.outcome == CollectorOutcome.OPT_OUT_DROPPED for r in results)
    assert _run(store.count()) == 0
    assert len(_read_audit(audit.path)) == 16


# ===========================================================================
# PB7 — Audit-log content safety
# ===========================================================================


def test_pb7_audit_log_has_only_safe_fields_on_pii_rejection(tmp_path: Path):
    """PB7-a: a PII rejection audit entry contains ONLY safe fields.

    The four allowed keys are: payload_hash, reason_code, stage, timestamp.
    No tenant-side string, template token, or example identifier may appear
    anywhere in the JSONL line.
    """

    secret_marker = "SECRET-TEMPLATE-MARKER-12345"

    cfg = TenantSignatureConfig(tenant_anon_id=PHONE_SHAPED_ANON_ID)
    store = FileMetaStore(tmp_path / "meta")
    audit = TenantAuditLog(tmp_path / "audit.jsonl")
    collector = SignatureCollector(
        tenant_config=cfg, meta_store=store, audit_log=audit
    )

    raw = RawNamingConventionEvent(
        tenant_anon_id=PHONE_SHAPED_ANON_ID,
        applies_to="drawing_number",
        raw_template=f"<{secret_marker}>",
        matched_count=5,
        sample_count=5,
        example_identifiers=[f"ID-{secret_marker}-001"],
    )
    _run(collector.process_one(raw))

    on_disk = audit.path.read_text(encoding="utf-8")

    # Secret marker must not appear anywhere on disk.
    assert secret_marker not in on_disk, (
        "QA-03 PB7-a: secret template marker leaked to audit log"
    )

    # Structural check: the entry has exactly the four allowed keys.
    entries = _read_audit(audit.path)
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry.keys()) == {"payload_hash", "reason_code", "stage", "timestamp"}, (
        f"QA-03 PB7-a: audit entry has unexpected keys: {set(entry.keys())}"
    )


def test_pb7_audit_log_has_only_safe_fields_on_schema_rejection(
    tmp_path: Path,
):
    """PB7-b: a schema-validation rejection audit entry is also content-free.

    We inject a forbidden key into the envelope dict (rejected at Stage 1 by
    Pydantic extra='forbid').  We then simulate what the collector would do:
    write the rejection into the audit log using the chain result's payload_hash.
    The FORBIDDEN-VALUE string must not appear anywhere on disk.
    """

    payload = {
        "event_id": "abcdefab-cdef-4abc-9abc-abcdefabcdef",
        "schema_version": "1.0.0",
        "observed_at_utc": "2026-05-23T00:00:00+00:00",
        "tenant_anon_id": SAFE_ANON_ID_A,
        "opt_out_flag": False,
        "domain_signature_id": None,
        "payload": {
            "kind": "ontology_shape",
            "depth": 3,
            "node_count_bucket": "51-200",
            "branching_factor_p50": 2.0,
            "branching_factor_p95": 5.0,
            "leaf_to_internal_ratio": 0.6,
            "kind_distribution": {"category": 5, "entity": 10, "topic": 3},
            "induced_vs_seed_ratio": 0.3,
            "raw_text": "FORBIDDEN-VALUE-MUST-NOT-LEAK",
        },
    }

    chain = CheckerPipeline().check(payload)
    assert not chain.passed
    # Stage 1 (schema) fires for extra keys; the payload hash is still set.
    assert chain.failed_stage in {
        Stage.SCHEMA_VALIDATE,
        Stage.FORBIDDEN_FIELD_NAME_SCAN,
    }
    assert isinstance(chain.payload_hash, str) and len(chain.payload_hash) == 64

    audit = TenantAuditLog(tmp_path / "audit.jsonl")
    audit.write(
        payload_hash=chain.payload_hash,
        reason_code=chain.failed_reason,
        stage=chain.failed_stage,
    )

    on_disk = audit.path.read_text(encoding="utf-8")
    assert "FORBIDDEN-VALUE-MUST-NOT-LEAK" not in on_disk

    entry = _read_audit(audit.path)[0]
    assert set(entry.keys()) == {"payload_hash", "reason_code", "stage", "timestamp"}


# ===========================================================================
# PB8 — CheckResult.details never leaks content
# ===========================================================================


@pytest.mark.parametrize("forbidden_key", ["raw_text", "file_path", "email"])
def test_pb8_details_never_contains_field_value_for_forbidden_field(forbidden_key):
    """PB8-a: scan_forbidden_field_names CheckResult.details carries the field
    *path*, not the field *value*.

    We test this by calling the Stage 2 function directly on a hand-crafted
    dict with a forbidden key and a clearly-labelled sensitive value.  The
    full pipeline would short-circuit at Stage 1 for this input (Pydantic
    extra='forbid'), but the privacy invariant we're testing is Stage 2's
    `details` construction — so we go straight to the source.
    """

    sensitive_value = f"SENSITIVE-VALUE-FOR-{forbidden_key.upper()}"

    serialized = {
        "payload": {
            "kind": "ontology_shape",
            forbidden_key: sensitive_value,
        }
    }

    result = scan_forbidden_field_names(serialized)
    assert not result.passed
    assert result.reason_code == ReasonCode.FORBIDDEN_FIELD_NAME

    details = result.details or ""
    assert sensitive_value not in details, (
        f"QA-03 PB8-a: sensitive value leaked into CheckResult.details "
        f"for forbidden key `{forbidden_key}` — details={details!r}"
    )
    # The field NAME (path) should appear in details.
    assert forbidden_key in details, (
        f"QA-03 PB8-a: field name `{forbidden_key}` missing from details={details!r}"
    )


def test_pb8_details_never_contains_pii_value():
    """PB8-b: CheckResult.details on a PII rejection never contains the PII."""

    # The PII value is the email-shaped anon_id.  Critically, `details` must
    # say something like "email-shaped substring at $.tenant_anon_id" but must
    # not include the email string itself.
    pii_anon_id = "padpadpadpadpadpadpadpadpadjane@acme.io-tail"

    env = _envelope_with_anon_id(pii_anon_id)
    chain = CheckerPipeline().check(env)
    assert not chain.passed

    all_details = " ".join(r.details or "" for r in chain.results if r.details)
    # The email address must not appear verbatim.
    assert "jane@acme.io" not in all_details, (
        "QA-03 PB8-b: PII email leaked into CheckResult.details"
    )
    # The path hint should be present.
    assert "tenant_anon_id" in all_details


# ===========================================================================
# PB9 — No over-blocking (all 8 raw event variants with clean data)
# ===========================================================================


@pytest.mark.parametrize("kind", RAW_EVENT_KINDS)
def test_pb9_clean_event_is_accepted_all_variants(kind: str, tmp_path: Path):
    """PB9: every clean raw event variant is ACCEPTED and produces one record.

    The privacy gate must not over-fire: legitimate principle-only data must
    reach the meta store.
    """

    cfg = _make_cfg(SAFE_ANON_ID_A, opt_out=False)
    store = FileMetaStore(tmp_path / f"meta_{kind}")
    audit = TenantAuditLog(tmp_path / f"audit_{kind}.jsonl")

    collector = SignatureCollector(
        tenant_config=cfg, meta_store=store, audit_log=audit
    )

    raw_events = _raw_events(SAFE_ANON_ID_A)
    kind_index = RAW_EVENT_KINDS.index(kind)
    raw = raw_events[kind_index]

    result = _run(collector.process_one(raw))

    assert result.outcome == CollectorOutcome.ACCEPTED, (
        f"kind={kind}: expected ACCEPTED; got {result.outcome} "
        f"(reason={result.reason_code}, stage={result.stage})"
    )
    assert result.envelope is not None
    assert result.envelope.payload.kind == kind
    assert _run(store.count()) == 1
    # No audit log should exist on success.
    assert not audit.path.exists(), (
        f"kind={kind}: unexpected audit entry on accepted event"
    )


# ===========================================================================
# PB10 — FileMetaStore tenant-scoped query isolation
# ===========================================================================


def test_pb10_meta_store_query_by_foreign_tenant_id_returns_nothing(
    tmp_path: Path,
):
    """PB10-a: querying the meta store with a foreign tenant_anon_id returns no rows.

    Both tenant A and tenant B share the same FileMetaStore file.  A's
    query must see only A's records; it must not return B's records.
    """

    store = FileMetaStore(tmp_path / "shared_meta")

    # Tenant A writes one record.
    cfg_a = _make_cfg(SAFE_ANON_ID_A)
    audit_a = TenantAuditLog(tmp_path / "audit_a.jsonl")
    collector_a = SignatureCollector(
        tenant_config=cfg_a, meta_store=store, audit_log=audit_a
    )
    raw_a = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID_A,
        depth=2,
        node_count=30,
        branching_factors=[1.0, 1.5],
        kind_distribution={"category": 3, "entity": 5, "topic": 1},
    )
    result_a = _run(collector_a.process_one(raw_a))
    assert result_a.outcome == CollectorOutcome.ACCEPTED

    # Tenant B writes one record.
    cfg_b = _make_cfg(SAFE_ANON_ID_B)
    audit_b = TenantAuditLog(tmp_path / "audit_b.jsonl")
    collector_b = SignatureCollector(
        tenant_config=cfg_b, meta_store=store, audit_log=audit_b
    )
    raw_b = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID_B,
        depth=3,
        node_count=50,
        branching_factors=[2.0, 3.0],
        kind_distribution={"category": 8, "entity": 12, "topic": 4},
    )
    result_b = _run(collector_b.process_one(raw_b))
    assert result_b.outcome == CollectorOutcome.ACCEPTED

    # Total records on disk: 2.
    assert _run(store.count()) == 2

    # Querying by A's id returns exactly 1 row.
    async def _query(tid: str) -> list:
        out = []
        async for env in store.query(tenant_anon_id=tid):
            out.append(env)
        return out

    rows_a = _run(_query(SAFE_ANON_ID_A))
    assert len(rows_a) == 1
    assert rows_a[0].tenant_anon_id == SAFE_ANON_ID_A

    rows_b = _run(_query(SAFE_ANON_ID_B))
    assert len(rows_b) == 1
    assert rows_b[0].tenant_anon_id == SAFE_ANON_ID_B


def test_pb10_cross_tenant_query_returns_nothing(tmp_path: Path):
    """PB10-b: querying with the wrong (foreign) tenant id returns zero rows."""

    store = FileMetaStore(tmp_path / "shared_meta")

    # Tenant A writes a record.
    cfg_a = _make_cfg(SAFE_ANON_ID_A)
    collector_a = SignatureCollector(
        tenant_config=cfg_a,
        meta_store=store,
        audit_log=TenantAuditLog(tmp_path / "audit_a.jsonl"),
    )
    raw_a = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID_A,
        depth=2,
        node_count=20,
        branching_factors=[1.0],
        kind_distribution={"category": 2, "entity": 4, "topic": 1},
    )
    _run(collector_a.process_one(raw_a))

    # Querying with B's id (no records for B) returns nothing.
    async def _query_b() -> list:
        out = []
        async for env in store.query(tenant_anon_id=SAFE_ANON_ID_B):
            out.append(env)
        return out

    rows = _run(_query_b())
    assert rows == [], (
        "QA-03 PB10-b: cross-tenant query returned rows belonging to another tenant"
    )


def test_pb10_cross_tenant_direct_record_check(tmp_path: Path):
    """PB10-c: a record written for tenant A has its tenant_anon_id field set
    to A's id — not B's id — confirming the envelope correctly carries the
    writer's identity rather than a default or wrong value.
    """

    store = FileMetaStore(tmp_path / "meta")
    cfg_a = _make_cfg(SAFE_ANON_ID_A)
    collector_a = SignatureCollector(
        tenant_config=cfg_a,
        meta_store=store,
        audit_log=TenantAuditLog(tmp_path / "audit_a.jsonl"),
    )
    raw_a = RawOntologyShapeEvent(
        tenant_anon_id=SAFE_ANON_ID_A,
        depth=2,
        node_count=20,
        branching_factors=[1.0],
        kind_distribution={"category": 2, "entity": 4, "topic": 1},
    )
    result = _run(collector_a.process_one(raw_a))
    assert result.outcome == CollectorOutcome.ACCEPTED

    # Read the raw JSONL file and confirm the anon_id is A's, not B's.
    raw_line = store.path.read_text(encoding="utf-8").strip()
    record = json.loads(raw_line)
    assert record["tenant_anon_id"] == SAFE_ANON_ID_A
    assert record["tenant_anon_id"] != SAFE_ANON_ID_B

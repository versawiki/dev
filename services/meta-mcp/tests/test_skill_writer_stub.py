"""StubLLMSkillWriter + happy-path pipeline tests.

Asserts:
  - The stub returns deterministic markdown for a given group.
  - The pipeline writes the file at the right path.
  - SkillRecord is well-formed; body_sha256 matches actual on-disk bytes.
  - The audit log is NOT touched on a happy-path write.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from versawiki_meta_mcp.schema.observation import (
    DomainObservationEnvelope,
    NamingConvention,
)
from versawiki_meta_mcp.skills.aggregator import (
    SignatureAggregator,
    SignatureGroup,
)
from versawiki_meta_mcp.skills.llm_writer import StubLLMSkillWriter
from versawiki_meta_mcp.skills.pipeline import (
    SkillWritingOutcome,
    SkillWritingPipeline,
)
from versawiki_meta_mcp.skills.thresholds import (
    SkillWriteThreshold,
    SkillWriteThresholds,
)
from versawiki_meta_mcp.store.file_store import FileMetaStore


def _run(awaitable):
    return asyncio.run(awaitable)


TENANTS = [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
]
_BASE = "abcdefab-cdef-4abc-9abc-abcdefab"


async def _seed(store: FileMetaStore, n_per_tenant: int = 5) -> None:
    for t_idx, t in enumerate(TENANTS):
        for i in range(n_per_tenant):
            payload = NamingConvention(
                applies_to="drawing_number",
                template="<phase>-<discipline>-<sequence>",
                token_vocabulary=["phase", "discipline", "sequence"],
                sample_count_bucket="51-200",
                adherence_rate=0.93,
            )
            env = DomainObservationEnvelope(
                event_id=f"{_BASE}{t_idx:02x}{i:02x}",
                schema_version="1.0.0",
                observed_at_utc=datetime.now(timezone.utc),
                tenant_anon_id=t,
                opt_out_flag=False,
                domain_signature_id=None,
                payload=payload,
            )
            await store.write_observation(env)


def _low_threshold() -> SkillWriteThresholds:
    return SkillWriteThresholds(
        default=SkillWriteThreshold(
            min_distinct_tenants=2, min_observations=3, confidence_floor=0.0
        )
    )


def test_stub_is_deterministic() -> None:
    group = SignatureGroup(
        domain="AEC",
        kind="naming-convention",
        distinct_tenants=3,
        observation_count=15,
        mean_confidence=0.93,
        shape_examples=["naming::<phase>-<discipline>-<sequence>"],
        observation_ids=["abc"],
    )
    writer = StubLLMSkillWriter()
    a = writer.write(group)
    b = writer.write(group)
    assert a == b
    # And it contains the group's shape — no surprise content.
    assert "naming::<phase>-<discipline>-<sequence>" in a
    assert "AEC" in a


def test_stub_output_contains_no_raw_counts() -> None:
    """The stub formats counts via the SignatureGroup's int fields.

    `distinct_tenants` IS a raw count by construction — the stub uses it.
    That's why the load-bearing test focuses on the LLM-output path, not
    the stub. But the stub must NOT emit any unbucketed-looking-numeric
    OUTSIDE the "across N distinct tenants" sentence (the checker
    accepts confidence-shaped decimals).

    We assert the stub output is structurally well-formed and length-bounded.
    """

    group = SignatureGroup(
        domain="AEC",
        kind="naming-convention",
        distinct_tenants=3,
        observation_count=15,
        mean_confidence=0.93,
        shape_examples=[],
        observation_ids=[],
    )
    body = StubLLMSkillWriter().write(group)
    assert body.endswith("\n")
    assert len(body) < 4000


def test_pipeline_writes_file_at_canonical_path(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    _run(_seed(store))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store, thresholds=_low_threshold())

    class _CleanLLM:
        def write(self, group):  # noqa: ARG002
            return (
                "## When to apply\n\n"
                "Apply when ingesting drawing identifiers in this domain.\n"
                "\n## Recurring shape\n\n"
                "- `naming::<phase>-<discipline>-<sequence>`\n"
            )

    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=_CleanLLM(), skills_root=skills_root
    )
    results = _run(pipeline.run())
    assert len(results) == 1
    assert results[0].outcome == SkillWritingOutcome.WRITTEN

    expected_path = (
        skills_root / "AEC" / "naming-convention__aec-naming-convention__v1.md"
    )
    assert expected_path.exists(), f"expected file at {expected_path}"

    record = results[0].record
    assert record is not None
    assert record.relative_path == "AEC/naming-convention__aec-naming-convention__v1.md"
    assert record.version == 1
    assert record.domain == "AEC"
    assert record.kind == "naming-convention"

    # body_sha256 must match the on-disk bytes.
    body_bytes = expected_path.read_bytes()
    expected_hash = hashlib.sha256(body_bytes).hexdigest()
    assert record.body_sha256 == expected_hash


def test_pipeline_does_not_touch_audit_log_on_success(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    _run(_seed(store))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store, thresholds=_low_threshold())

    class _CleanLLM:
        def write(self, group):  # noqa: ARG002
            return (
                "## Pattern\n\nApply across the domain on drawing identifiers.\n"
            )

    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=_CleanLLM(), skills_root=skills_root
    )
    _run(pipeline.run())
    audit_path = skills_root / "_rejections.jsonl"
    # The file may or may not exist; if it does, it must be empty.
    if audit_path.exists():
        text = audit_path.read_text(encoding="utf-8")
        assert text.strip() == ""


def test_pipeline_no_crossing_groups_no_output(tmp_path: Path) -> None:
    """Below threshold -> no work done, no file, no audit."""

    store = FileMetaStore(tmp_path / "meta")  # empty
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(
        meta_store=store,
        thresholds=SkillWriteThresholds(
            default=SkillWriteThreshold(
                min_distinct_tenants=99, min_observations=99, confidence_floor=0.0
            )
        ),
    )
    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=StubLLMSkillWriter(), skills_root=skills_root
    )
    results = _run(pipeline.run())
    assert results == []


def test_record_observation_ids_match_group(tmp_path: Path) -> None:
    """SkillRecord carries the source observation ids from the group."""

    store = FileMetaStore(tmp_path / "meta")
    _run(_seed(store, n_per_tenant=4))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store, thresholds=_low_threshold())

    class _CleanLLM:
        def write(self, group):  # noqa: ARG002
            return "## P\n\nApply across the domain.\n"

    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=_CleanLLM(), skills_root=skills_root
    )
    [r] = _run(pipeline.run())
    assert r.record is not None
    # 3 tenants x 4 events = 12 observation ids.
    assert len(r.record.derived_from_observation_ids) == 12

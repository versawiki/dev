"""Threshold gate behaviour at the pipeline level.

Boundary cases that test_aggregator.py covers from the aggregator side,
now exercised through the full pipeline:

  - Below min_distinct_tenants -> nothing written.
  - Below min_observations -> nothing written.
  - Above all + LLM passes checker -> file written + record returned.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from versawiki_meta_mcp.schema.observation import (
    DomainObservationEnvelope,
    NamingConvention,
)
from versawiki_meta_mcp.skills.aggregator import SignatureAggregator, SignatureGroup
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


_BASE = "abcdefab-cdef-4abc-9abc-abcdefab"
TENANTS = [
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
]


async def _seed(store: FileMetaStore, n_tenants: int, n_per_tenant: int) -> None:
    for t_idx, t in enumerate(TENANTS[:n_tenants]):
        for i in range(n_per_tenant):
            env = DomainObservationEnvelope(
                event_id=f"{_BASE}{t_idx:02x}{i:02x}",
                schema_version="1.0.0",
                observed_at_utc=datetime.now(timezone.utc),
                tenant_anon_id=t,
                opt_out_flag=False,
                domain_signature_id=None,
                payload=NamingConvention(
                    applies_to="drawing_number",
                    template="<phase>-<discipline>-<sequence>",
                    token_vocabulary=["phase", "discipline", "sequence"],
                    sample_count_bucket="51-200",
                    adherence_rate=0.93,
                ),
            )
            await store.write_observation(env)


class _CleanLLM:
    def write(self, group):  # noqa: ARG002
        return "## When\n\nApply across the domain on drawing identifiers.\n"


def test_default_thresholds_have_expected_values() -> None:
    """Locks the documented defaults: 3 tenants / 25 obs / 0.65 confidence."""

    t = SkillWriteThreshold()
    assert t.min_distinct_tenants == 3
    assert t.min_observations == 25
    assert t.confidence_floor == 0.65


def test_below_min_distinct_tenants_no_skill_written(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    # 2 tenants only — below default 3.
    _run(_seed(store, n_tenants=2, n_per_tenant=20))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store)  # default thresholds
    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=_CleanLLM(), skills_root=skills_root
    )
    results = _run(pipeline.run())
    assert results == []
    # Skills root may have been created but no skill file under any domain.
    assert not list(skills_root.rglob("*.md"))


def test_below_min_observations_no_skill_written(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    # 3 tenants but only 5 events each = 15 < default 25.
    _run(_seed(store, n_tenants=3, n_per_tenant=5))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store)
    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=_CleanLLM(), skills_root=skills_root
    )
    results = _run(pipeline.run())
    assert results == []
    assert not list(skills_root.rglob("*.md"))


def test_above_all_thresholds_skill_written(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    # 3 tenants x 10 events = 30 >= 25. naming_convention confidence
    # (adherence_rate) is 0.93 >= 0.65.
    _run(_seed(store, n_tenants=3, n_per_tenant=10))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store)  # default thresholds
    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=_CleanLLM(), skills_root=skills_root
    )
    [r] = _run(pipeline.run())
    assert r.outcome == SkillWritingOutcome.WRITTEN
    assert r.record is not None
    assert (skills_root / r.record.relative_path).exists()


def test_confidence_floor_blocks_low_confidence_group(tmp_path: Path) -> None:
    """Adherence rate 0.2 is below the 0.65 floor -> no skill."""

    store = FileMetaStore(tmp_path / "meta")
    for t_idx, t in enumerate(TENANTS):
        for i in range(10):
            env = DomainObservationEnvelope(
                event_id=f"{_BASE}{t_idx:02x}{i:02x}",
                schema_version="1.0.0",
                observed_at_utc=datetime.now(timezone.utc),
                tenant_anon_id=t,
                opt_out_flag=False,
                domain_signature_id=None,
                payload=NamingConvention(
                    applies_to="drawing_number",
                    template="<phase>-<discipline>-<sequence>",
                    token_vocabulary=["phase", "discipline", "sequence"],
                    sample_count_bucket="51-200",
                    adherence_rate=0.20,  # below floor
                ),
            )
            _run(store.write_observation(env))

    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store)
    pipeline = SkillWritingPipeline(
        aggregator=agg, llm_writer=_CleanLLM(), skills_root=skills_root
    )
    results = _run(pipeline.run())
    assert results == []

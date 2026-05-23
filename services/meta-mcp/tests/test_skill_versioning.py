"""Versioning behaviour: same (domain, kind, title) -> v2; old file preserved."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from versawiki_meta_mcp.schema.observation import (
    DomainObservationEnvelope,
    NamingConvention,
)
from versawiki_meta_mcp.skills.aggregator import SignatureAggregator
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


async def _seed(store: FileMetaStore, n_per_tenant: int = 5) -> None:
    for t_idx, t in enumerate(TENANTS):
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


def _low_threshold() -> SkillWriteThresholds:
    return SkillWriteThresholds(
        default=SkillWriteThreshold(
            min_distinct_tenants=2, min_observations=3, confidence_floor=0.0
        )
    )


_BODIES = [
    "## Pattern\n\nApply across the domain on identifiers.\n",
    "## Pattern\n\nApply broadly when ingesting drawing identifiers.\n",
    "## Pattern\n\nApply with confidence on drawing identifiers.\n",
]


def test_second_write_creates_v2(tmp_path: Path) -> None:
    store = FileMetaStore(tmp_path / "meta")
    _run(_seed(store))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store, thresholds=_low_threshold())

    class _LLM:
        def __init__(self, content: str) -> None:
            self._content = content

        def write(self, group):  # noqa: ARG002
            return self._content

    p1 = SkillWritingPipeline(
        aggregator=agg, llm_writer=_LLM(_BODIES[0]), skills_root=skills_root
    )
    [r1] = _run(p1.run())
    assert r1.record is not None, f"v1 expected; got outcome {r1.outcome}"
    assert r1.record.version == 1

    p2 = SkillWritingPipeline(
        aggregator=agg, llm_writer=_LLM(_BODIES[1]), skills_root=skills_root
    )
    [r2] = _run(p2.run())
    assert r2.record is not None
    assert r2.record.version == 2

    v1_path = skills_root / r1.record.relative_path
    v2_path = skills_root / r2.record.relative_path
    assert v1_path.exists()
    assert v2_path.exists()
    assert v1_path.read_text(encoding="utf-8") == _BODIES[0]
    assert v2_path.read_text(encoding="utf-8") == _BODIES[1]


def test_third_write_creates_v3(tmp_path: Path) -> None:
    """Confirms monotonic — not an off-by-one."""

    store = FileMetaStore(tmp_path / "meta")
    _run(_seed(store))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store, thresholds=_low_threshold())

    class _LLM:
        def __init__(self, content: str) -> None:
            self._content = content

        def write(self, group):  # noqa: ARG002
            return self._content

    for body in _BODIES:
        p = SkillWritingPipeline(
            aggregator=agg, llm_writer=_LLM(body), skills_root=skills_root
        )
        [r] = _run(p.run())
        assert r.record is not None, f"expected write, got {r.outcome}"

    files = sorted(
        (skills_root / "AEC").glob("naming-convention__aec-naming-convention__v*.md")
    )
    assert len(files) == 3
    assert files[0].name.endswith("__v1.md")
    assert files[-1].name.endswith("__v3.md")


def test_versioning_preserves_old_record(tmp_path: Path) -> None:
    """A new write under the same (domain, kind, title) does not touch v1."""

    store = FileMetaStore(tmp_path / "meta")
    _run(_seed(store))
    skills_root = tmp_path / "skills"
    agg = SignatureAggregator(meta_store=store, thresholds=_low_threshold())

    class _LLM:
        def __init__(self, content: str) -> None:
            self._content = content

        def write(self, group):  # noqa: ARG002
            return self._content

    p1 = SkillWritingPipeline(
        aggregator=agg, llm_writer=_LLM(_BODIES[0]), skills_root=skills_root
    )
    [r1] = _run(p1.run())
    v1_path = skills_root / r1.record.relative_path
    v1_mtime_before = v1_path.stat().st_mtime_ns

    # Subsequent run.
    p2 = SkillWritingPipeline(
        aggregator=agg, llm_writer=_LLM(_BODIES[1]), skills_root=skills_root
    )
    _run(p2.run())

    # v1 file unchanged.
    v1_mtime_after = v1_path.stat().st_mtime_ns
    assert v1_mtime_after == v1_mtime_before
    # And its content is identical.
    assert v1_path.read_text(encoding="utf-8") == _BODIES[0]

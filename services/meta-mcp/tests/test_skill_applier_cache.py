"""SkillApplier cache: hits on second call; invalidates on mtime bump."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from versawiki_meta_mcp.applier.applier import SkillApplier
from versawiki_meta_mcp.applier.cache import signature_hash
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig


_TENANT_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


def _run(awaitable):
    return asyncio.run(awaitable)


def _seed_aec_skill_tree(root: Path) -> None:
    aec = root / "AEC"
    aec.mkdir(parents=True, exist_ok=True)
    (aec / "ingestion-pattern__aec-doc-types__v1.md").write_text(
        "AEC corpora dominated by drawing, specification, rfi.\n",
        encoding="utf-8",
    )


def _aec_tenant_config() -> TenantSignatureConfig:
    return TenantSignatureConfig(
        tenant_anon_id=_TENANT_ID,
        type_vocab={"Drawing": "drawing", "Spec": "specification", "RFI": "rfi"},
    )


def test_second_call_hits_cache(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _seed_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root, min_score=0.0)
    config = _aec_tenant_config()

    first = _run(applier.apply("tenant-A", config, "classifier"))
    assert first is not None
    sig = signature_hash(config)
    cached = applier.cache.get(
        config.tenant_anon_id, sig, current_watermark=applier.loader.watermark
    )
    assert cached is not None

    # Second call: same key + same watermark — must still be cached.
    second = _run(applier.apply("tenant-A", config, "classifier"))
    assert second == first
    cached_again = applier.cache.get(
        config.tenant_anon_id, sig, current_watermark=applier.loader.watermark
    )
    assert cached_again is not None


def test_cache_invalidates_on_skill_tree_mtime_change(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _seed_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root, min_score=0.0)
    config = _aec_tenant_config()

    first = _run(applier.apply("tenant-A", config, "classifier"))
    assert first is not None
    sig = signature_hash(config)

    # Write a new skill file and bump its mtime to a strictly-future moment
    # so the watermark moves past anything the cache pinned.
    new_skill = root / "AEC" / "naming-convention__aec-naming__v1.md"
    new_skill.write_text(
        "Naming: AEC drawings carry phase, discipline tokens.\n",
        encoding="utf-8",
    )
    future = time.time() + 5.0
    os.utime(new_skill, (future, future))
    # Also bump the parent dir so the watermark visibly moves.
    os.utime(new_skill.parent, (future, future))

    # The cache lookup with the NEW watermark must not return the
    # pre-write entry.
    applier.loader.load()
    new_watermark = applier.loader.watermark
    stale = applier.cache.get(
        config.tenant_anon_id, sig, current_watermark=new_watermark
    )
    assert stale is None

    # And a fresh apply() now reflects the additional skill.
    second = _run(applier.apply("tenant-A", config, "classifier"))
    assert second is not None
    assert "Naming:" in second
    # First text had only the doc-types skill; new text has both.
    assert second != first


def test_cache_keys_differ_per_tenant(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _seed_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root, min_score=0.0)
    config_a = _aec_tenant_config()
    config_b = TenantSignatureConfig(
        tenant_anon_id="cccccccc-cccc-4ccc-9ccc-cccccccccccc",
        type_vocab=dict(config_a.type_vocab),
    )

    _run(applier.apply("tenant-A", config_a, "classifier"))
    _run(applier.apply("tenant-B", config_b, "classifier"))
    # Two distinct tenants -> two cache entries.
    assert applier.cache.size == 2

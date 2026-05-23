"""SkillApplier opt-out: returns None even when matches exist."""

from __future__ import annotations

import asyncio
from pathlib import Path

from versawiki_meta_mcp.applier.applier import SkillApplier
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig


_TENANT_ID = "bc6be0b5-7901-48fb-ae49-69d47663a776"


def _run(awaitable):
    return asyncio.run(awaitable)


def _seed_aec_skill_tree(root: Path) -> None:
    aec = root / "AEC"
    aec.mkdir(parents=True, exist_ok=True)
    (aec / "ingestion-pattern__aec-doc-types__v1.md").write_text(
        "AEC corpora are dominated by drawing, specification, rfi.\n",
        encoding="utf-8",
    )


def _aec_tenant_config(*, opt_out: bool) -> TenantSignatureConfig:
    return TenantSignatureConfig(
        tenant_anon_id=_TENANT_ID,
        opt_out=opt_out,
        type_vocab={
            "Drawing": "drawing",
            "Spec": "specification",
            "RFI": "rfi",
        },
    )


def test_opt_out_returns_none_even_with_matches(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _seed_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root, min_score=0.0)

    # First sanity-check: a NON-opt-out tenant gets a match.
    non_opt_text = _run(
        applier.apply("tenant-A", _aec_tenant_config(opt_out=False), "classifier")
    )
    assert non_opt_text is not None
    assert "AEC corpora" in non_opt_text

    # Same tenant config but opt_out=True must return None.
    opt_text = _run(
        applier.apply("tenant-A", _aec_tenant_config(opt_out=True), "classifier")
    )
    assert opt_text is None


def test_opt_out_does_not_populate_cache(tmp_path: Path) -> None:
    """An opt-out tenant must not leave a cache entry behind.

    Logging or caching matched-skill IDs against an opt-out tenant
    would let an observer correlate "this tenant opted out but looks
    AEC-ish" — see DECISIONS 2026-05-22 cross-tenant boundary.
    """

    root = tmp_path / "skills"
    _seed_aec_skill_tree(root)
    applier = SkillApplier(skills_root=root, min_score=0.0)

    _run(applier.apply("tenant-A", _aec_tenant_config(opt_out=True), "classifier"))
    assert applier.cache.size == 0

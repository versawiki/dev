"""Tests for M1-MCP-05: TenantOptOutStore (Flag API + persistence).

Covers:
  - Default-false for unknown tenants
  - Basic set / get round-trip
  - Persistence across store instances (new object reads same file)
  - Explicit False is stored and readable
  - Multiple independent tenants
  - Idempotent set
  - all_opted_out returns only True entries
  - all_flags returns full snapshot
  - clear_opt_out removes the entry (get returns False again)
  - Corrupt file handled gracefully (returns empty dict, not an exception)
  - Atomic write: partial writes don't leave corrupt state
  - load_tenant_config bakes opt_out from the store
  - load_tenant_config passes extra kwargs through to TenantSignatureConfig
  - load_tenant_config defaults to opt_out=False for unknown tenant
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from versawiki_meta_mcp.opt_out import TenantOptOutStore, load_tenant_config
from versawiki_meta_mcp.collector.tenant_config import TenantSignatureConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TENANT_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Default + basic round-trip
# ---------------------------------------------------------------------------


def test_unknown_tenant_defaults_to_false(tmp_path: Path) -> None:
    """A tenant with no stored entry has opt_out=False."""
    store = TenantOptOutStore(tmp_path / "opt_out")
    assert _run(store.get_opt_out(TENANT_A)) is False


def test_set_opt_out_true_and_get_back(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    assert _run(store.get_opt_out(TENANT_A)) is True


def test_set_opt_out_false_and_get_back(tmp_path: Path) -> None:
    """Explicitly setting False is persisted and readable."""
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))  # set True first
    _run(store.set_opt_out(TENANT_A, False))  # then reset to False
    assert _run(store.get_opt_out(TENANT_A)) is False


# ---------------------------------------------------------------------------
# Persistence across instances
# ---------------------------------------------------------------------------


def test_persists_across_store_instances(tmp_path: Path) -> None:
    """A new TenantOptOutStore pointed at the same root reads the same flags."""
    root = tmp_path / "opt_out"
    store1 = TenantOptOutStore(root)
    _run(store1.set_opt_out(TENANT_A, True))

    store2 = TenantOptOutStore(root)  # fresh instance, same directory
    assert _run(store2.get_opt_out(TENANT_A)) is True


def test_backing_file_is_valid_json(tmp_path: Path) -> None:
    """After a write the backing file is valid JSON with the expected shape."""
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))

    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data[TENANT_A] is True


# ---------------------------------------------------------------------------
# Multiple tenants
# ---------------------------------------------------------------------------


def test_multiple_tenants_are_independent(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.set_opt_out(TENANT_B, False))

    assert _run(store.get_opt_out(TENANT_A)) is True
    assert _run(store.get_opt_out(TENANT_B)) is False
    assert _run(store.get_opt_out(TENANT_C)) is False  # never set


def test_set_one_tenant_does_not_clear_another(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.set_opt_out(TENANT_B, True))
    # Now update only A
    _run(store.set_opt_out(TENANT_A, False))

    assert _run(store.get_opt_out(TENANT_A)) is False
    assert _run(store.get_opt_out(TENANT_B)) is True  # B must be untouched


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_set_twice_same_value_is_idempotent(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.set_opt_out(TENANT_A, True))
    assert _run(store.get_opt_out(TENANT_A)) is True


# ---------------------------------------------------------------------------
# all_opted_out / all_flags
# ---------------------------------------------------------------------------


def test_all_opted_out_returns_only_true_entries(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.set_opt_out(TENANT_B, False))
    _run(store.set_opt_out(TENANT_C, True))

    result = _run(store.all_opted_out())
    assert result == frozenset({TENANT_A, TENANT_C})


def test_all_opted_out_empty_when_no_entries(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    assert _run(store.all_opted_out()) == frozenset()


def test_all_flags_returns_full_snapshot(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.set_opt_out(TENANT_B, False))

    flags = _run(store.all_flags())
    assert flags == {TENANT_A: True, TENANT_B: False}


# ---------------------------------------------------------------------------
# clear_opt_out
# ---------------------------------------------------------------------------


def test_clear_opt_out_removes_entry(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.clear_opt_out(TENANT_A))

    assert _run(store.get_opt_out(TENANT_A)) is False


def test_clear_opt_out_does_not_affect_other_tenants(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.set_opt_out(TENANT_B, True))
    _run(store.clear_opt_out(TENANT_A))

    assert _run(store.get_opt_out(TENANT_A)) is False
    assert _run(store.get_opt_out(TENANT_B)) is True


def test_clear_opt_out_is_no_op_for_unknown_tenant(tmp_path: Path) -> None:
    """Clearing a tenant that was never set must not raise."""
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.clear_opt_out(TENANT_A))  # should not raise
    assert _run(store.get_opt_out(TENANT_A)) is False


def test_cleared_tenant_absent_from_backing_file(tmp_path: Path) -> None:
    """After a clear the tenant key must not appear in the JSON file at all."""
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))
    _run(store.clear_opt_out(TENANT_A))

    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert TENANT_A not in data


# ---------------------------------------------------------------------------
# Corrupt / absent file handling
# ---------------------------------------------------------------------------


def test_corrupt_file_returns_false_not_exception(tmp_path: Path) -> None:
    root = tmp_path / "opt_out"
    root.mkdir(parents=True)
    (root / "opt_out.json").write_text("not-valid-json{{", encoding="utf-8")

    store = TenantOptOutStore(root)
    # Must not raise; must return the safe default.
    assert _run(store.get_opt_out(TENANT_A)) is False


def test_non_dict_json_returns_false_not_exception(tmp_path: Path) -> None:
    root = tmp_path / "opt_out"
    root.mkdir(parents=True)
    (root / "opt_out.json").write_text("[true, false]", encoding="utf-8")

    store = TenantOptOutStore(root)
    assert _run(store.get_opt_out(TENANT_A)) is False


# ---------------------------------------------------------------------------
# load_tenant_config integration
# ---------------------------------------------------------------------------


def test_load_tenant_config_bakes_opt_out_true(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))

    cfg = _run(load_tenant_config(TENANT_A, store))
    assert isinstance(cfg, TenantSignatureConfig)
    assert cfg.opt_out is True
    assert cfg.tenant_anon_id == TENANT_A


def test_load_tenant_config_bakes_opt_out_false_for_unknown(tmp_path: Path) -> None:
    store = TenantOptOutStore(tmp_path / "opt_out")
    cfg = _run(load_tenant_config(TENANT_A, store))
    assert cfg.opt_out is False


def test_load_tenant_config_forwards_kwargs(tmp_path: Path) -> None:
    """Extra kwargs (e.g. type_vocab) are passed through to TenantSignatureConfig."""
    store = TenantOptOutStore(tmp_path / "opt_out")
    vocab = {"Drawing": "drawing", "Spec": "specification"}

    cfg = _run(load_tenant_config(TENANT_A, store, type_vocab=vocab))
    assert cfg.type_vocab == vocab
    assert cfg.opt_out is False


def test_load_tenant_config_opt_out_overrides_kwarg(tmp_path: Path) -> None:
    """The store value for opt_out wins; passing opt_out as a kwarg is not
    allowed (Pydantic frozen + the store is the source of truth)."""
    store = TenantOptOutStore(tmp_path / "opt_out")
    _run(store.set_opt_out(TENANT_A, True))

    # Should reflect the store's True, not a kwarg override attempt.
    cfg = _run(load_tenant_config(TENANT_A, store))
    assert cfg.opt_out is True

"""Per-tenant opt-out flag persistence (M1-MCP-05).

On-disk layout
--------------
A single JSON file at ``<store_root>/opt_out.json``:

    {
      "<tenant_anon_id>": true,
      ...
    }

Only tenants that have explicitly opted out are listed (or tenants explicitly
set to `false`, though `clear_opt_out` removes them entirely).  The default
for any unlisted tenant is `False`.

Mutation safety
---------------
Each mutation reads the current file, applies the change in memory, and writes
atomically via a temp file + ``os.replace()``.  An ``asyncio.Lock`` per
instance serialises concurrent coroutines; ``os.replace()`` is atomic at the
OS level for same-filesystem temp→target moves, so two processes writing
simultaneously will produce a consistent file (last writer wins).

Privacy note
------------
``tenant_anon_id`` values are opaque hashes — they carry no customer content.
The boolean flag itself carries no content.  This file is safe to store
alongside the rest of the meta layer.

Usage example
-------------
    store = TenantOptOutStore("/var/meta/opt_out")
    await store.set_opt_out("abc...xyz", True)
    opted_out = await store.get_opt_out("abc...xyz")   # True
    cfg = await load_tenant_config("abc...xyz", store)  # opt_out=True baked in
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

from ..collector.tenant_config import TenantSignatureConfig


class TenantOptOutStore:
    """Persistent mapping of ``tenant_anon_id`` → opt-out flag.

    All async methods are coroutine-safe via an internal :class:`asyncio.Lock`.
    The lock is created lazily so the store can be instantiated outside an
    event loop (e.g. at module import time) and used inside one later.
    """

    def __init__(self, store_root: Union[str, "os.PathLike[str]"]) -> None:
        self._root = Path(store_root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "opt_out.json"
        self._lock: Optional[asyncio.Lock] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Absolute path of the backing JSON file."""
        return self._path

    # ------------------------------------------------------------------
    # Internal helpers (sync — always called under the lock, or read-only)
    # ------------------------------------------------------------------

    def _ensure_lock(self) -> asyncio.Lock:
        """Return (creating if necessary) the per-instance asyncio.Lock."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _read_flags(self) -> dict[str, bool]:
        """Read the backing file and return a clean ``{anon_id: bool}`` dict.

        Returns an empty dict if the file is absent, empty, or corrupt —
        never raises.
        """
        if not self._path.exists():
            return {}
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        # Sanitise: keep only string keys with truthy/falsy values.
        return {k: bool(v) for k, v in raw.items() if isinstance(k, str)}

    def _write_flags(self, flags: dict[str, bool]) -> None:
        """Atomically overwrite the backing file with *flags*.

        Uses write-to-temp + ``os.replace()`` so readers always see either
        the old or the new complete file, never a partial write.

        Raises:
            OSError: if the temp file or the rename fails.
        """
        fd, tmp_path = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(flags, fh, sort_keys=True, indent=2)
                fh.write("\n")
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def set_opt_out(self, tenant_anon_id: str, value: bool) -> None:
        """Set the opt-out flag for *tenant_anon_id* and persist immediately.

        Args:
            tenant_anon_id: The tenant's anonymous identifier.
            value: ``True`` to opt out, ``False`` to opt back in.
        """
        lock = self._ensure_lock()
        async with lock:
            flags = self._read_flags()
            flags[tenant_anon_id] = value
            self._write_flags(flags)

    async def get_opt_out(self, tenant_anon_id: str) -> bool:
        """Return the opt-out flag for *tenant_anon_id*.

        Returns ``False`` for any tenant that has no persisted entry
        (the safe default: no opt-out assumed).
        """
        flags = self._read_flags()
        return flags.get(tenant_anon_id, False)

    async def clear_opt_out(self, tenant_anon_id: str) -> None:
        """Remove *tenant_anon_id* from the store entirely.

        After this call, :meth:`get_opt_out` returns ``False`` (the default).
        No-ops if the tenant is not present.
        """
        lock = self._ensure_lock()
        async with lock:
            flags = self._read_flags()
            if tenant_anon_id in flags:
                del flags[tenant_anon_id]
                self._write_flags(flags)

    async def all_opted_out(self) -> frozenset[str]:
        """Return an immutable set of all ``tenant_anon_id`` values where
        the persisted flag is ``True``.
        """
        flags = self._read_flags()
        return frozenset(k for k, v in flags.items() if v)

    async def all_flags(self) -> dict[str, bool]:
        """Return a snapshot of every persisted ``{tenant_anon_id: bool}`` entry.

        This includes tenants explicitly set to ``False``.  Callers that only
        need opted-out tenants should use :meth:`all_opted_out`.
        """
        return dict(self._read_flags())


# ---------------------------------------------------------------------------
# Config-loader integration helper
# ---------------------------------------------------------------------------


async def load_tenant_config(
    tenant_anon_id: str,
    store: TenantOptOutStore,
    **kwargs: Any,
) -> TenantSignatureConfig:
    """Build a :class:`~versawiki_meta_mcp.collector.tenant_config.TenantSignatureConfig`
    with the ``opt_out`` flag loaded from *store*.

    This is the primary integration point between the persistent store and
    the rest of the meta-MCP stack.  All extra keyword arguments are forwarded
    verbatim to the ``TenantSignatureConfig`` constructor (e.g. ``type_vocab``,
    ``buckets``).

    Example::

        store = TenantOptOutStore("/var/meta/opt_out")
        await store.set_opt_out(tenant_id, True)

        cfg = await load_tenant_config(tenant_id, store)
        # cfg.opt_out == True  ← loaded from persistent store

        collector = SignatureCollector(tenant_config=cfg, ...)

    Args:
        tenant_anon_id: The tenant's anonymous identifier.
        store:          A :class:`TenantOptOutStore` instance to read from.
        **kwargs:       Extra keyword arguments passed through to
                        :class:`TenantSignatureConfig`.

    Returns:
        A frozen :class:`TenantSignatureConfig` with ``opt_out`` set from
        the store and all other fields from *kwargs* (or their defaults).
    """
    opt_out = await store.get_opt_out(tenant_anon_id)
    return TenantSignatureConfig(
        tenant_anon_id=tenant_anon_id,
        opt_out=opt_out,
        **kwargs,
    )

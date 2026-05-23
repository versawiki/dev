"""`AppliedSkillCache` — per-tenant LRU of (signature_hash) -> matches.

We don't want to re-run the matcher on every ingestion event. Most
tenants' signature config doesn't change between events; even when it
does, the cache key (a stable hash of the relevant config fields)
moves with it, so a stale entry isn't reachable.

Invalidation rule:
  * The cache stores the `SkillLibraryLoader`'s mtime watermark
    alongside each entry. On lookup, if the loader's current watermark
    differs from the entry's watermark, the entry is evicted. This is
    the contract the writer (`skills.pipeline`) implicitly upholds: a
    new on-disk skill file changes some file's mtime, which moves the
    loader's watermark, which evicts caches that were built before the
    write.

Privacy posture:
  * Cache keys are `(tenant_anon_id, signature_hash)`. The
    `signature_hash` is a sha256 of the canonical-JSON of the
    tenant config's vocab-map keys/values plus the bool `opt_out`
    flag. Note opt-out tenants are excluded from caching at the
    applier layer — see `SkillApplier.apply` — so this hash never
    embeds an opt-out=True tenant.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from ..collector.tenant_config import TenantSignatureConfig
from .matcher import MatchedSkill


def signature_hash(tenant_config: TenantSignatureConfig) -> str:
    """Stable sha256 of the cacheable parts of a `TenantSignatureConfig`.

    We hash sorted JSON of the six vocab maps + `tenant_anon_id` + the
    `opt_out` flag. The bucket boundaries are NOT in the hash — they're
    schema-level constants that don't vary per tenant in v1, and adding
    them would make the hash brittle without buying signal.

    Returns a 64-char hex string.
    """

    fingerprint = {
        "tenant_anon_id": tenant_config.tenant_anon_id,
        "opt_out": tenant_config.opt_out,
        "type_vocab": dict(sorted(tenant_config.type_vocab.items())),
        "relation_type_vocab": dict(sorted(tenant_config.relation_type_vocab.items())),
        "procedure_type_vocab": dict(sorted(tenant_config.procedure_type_vocab.items())),
        "naming_token_vocab": dict(sorted(tenant_config.naming_token_vocab.items())),
        "query_token_vocab": dict(sorted(tenant_config.query_token_vocab.items())),
        "state_vocab": dict(sorted(tenant_config.state_vocab.items())),
    }
    blob = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _CacheEntry:
    """One cached set of MatchedSkill results, pinned to a library watermark."""

    library_watermark: Optional[float]
    matches: tuple[MatchedSkill, ...]


class AppliedSkillCache:
    """LRU keyed by `(tenant_anon_id, signature_hash)` with watermark eviction.

    Capacity bounds memory; the default 1024 entries is generous given
    the v1 tenant count. Eviction is per-key: removing stale entries on
    lookup, not on a global rebuild, keeps the hot path predictable.
    """

    def __init__(self, *, max_entries: int = 1024) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._entries: "OrderedDict[tuple[str, str], _CacheEntry]" = OrderedDict()

    @property
    def size(self) -> int:
        return len(self._entries)

    def get(
        self,
        tenant_anon_id: str,
        sig_hash: str,
        *,
        current_watermark: Optional[float],
    ) -> Optional[tuple[MatchedSkill, ...]]:
        """Return the cached matches if still valid, else None.

        Validity = the entry's stored watermark equals `current_watermark`.
        A None on either side is treated as "no watermark"; only equal-or-
        both-None entries are valid.
        """

        key = (tenant_anon_id, sig_hash)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.library_watermark != current_watermark:
            # Stale: the underlying skill tree has changed since we cached.
            del self._entries[key]
            return None
        # LRU bump.
        self._entries.move_to_end(key)
        return entry.matches

    def put(
        self,
        tenant_anon_id: str,
        sig_hash: str,
        matches: tuple[MatchedSkill, ...],
        *,
        current_watermark: Optional[float],
    ) -> None:
        """Insert/replace a cache entry; evict LRU if at capacity."""

        key = (tenant_anon_id, sig_hash)
        self._entries[key] = _CacheEntry(
            library_watermark=current_watermark, matches=matches
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Drop all entries — used by tests and by explicit-reload hooks."""

        self._entries.clear()

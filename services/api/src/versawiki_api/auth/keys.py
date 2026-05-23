"""API-key domain model + store protocol + in-memory implementation.

Token format on the wire (header ``Authorization: Bearer ...``):

    vw_<prefix>_<secret>

- ``vw_`` is the literal product prefix.
- ``<prefix>`` is a URL-safe 12-char random string. Stored alongside
  the row; lets us look up by prefix and then argon2-verify the
  secret. Avoids scanning every key on every request.
- ``<secret>`` is a URL-safe 32-char random string. **The only part
  that is argon2-hashed.** We never store the raw secret; we return
  the assembled token to the caller exactly once at issue time.

The :class:`ApiKey` Pydantic model is the in-memory / on-the-wire
domain object. It deliberately omits ``key_hash`` because routes that
deal with ``ApiKey`` (the auth dep, the admin list endpoint) should
never see the hash.

:class:`ApiKeyStore` is the persistence boundary. BE-03 will add a
Postgres-backed implementation; today the in-memory implementation
ships so the auth middleware and admin routes are exercisable end-to-
end.

:class:`RedisCachedApiKeyStore` is a wrapper interface (no Redis
client wired yet) that BE-02-then-BE-03 can plug into. The wrapper
exists today so the call sites are stable.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .hashing import (
    TOKEN_PREFIX_LEN,
    TOKEN_SECRET_LEN,
    generate_token_parts,
    hash_token,
    verify_token,
)


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

class ApiKey(BaseModel):
    """An API key as the auth layer + admin routes see it.

    Never carries the raw token or the hash on the wire. The raw token
    is returned exactly once (at issue time) inside a separate response
    model (see :class:`IssuedApiKey` in the admin router).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Server-issued opaque key id.")
    tenant_id: str = Field(..., description="The owning tenant's id.")
    prefix: str = Field(
        ...,
        description=(
            "URL-safe 12-char prefix. Used for O(1) lookup; safe to log."
        ),
    )
    label: str | None = Field(
        default=None,
        description="Human-readable label (e.g. 'web-app', 'mcp-claude').",
    )
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    scopes: tuple[str, ...] = Field(
        default=("query",),
        description="Granted scopes. ``admin`` unlocks admin endpoints.",
    )

    # ----- back-compat shims so existing callers (see deps.py) still work -----

    @property
    def tenant_slug(self) -> str:
        """Stub bridge until the store joins tenants. BE-03 makes this real."""
        return self.tenant_id

    @property
    def is_stub(self) -> bool:  # noqa: D401 - matches the StubApiKey shim
        """``True`` if this key came from the in-memory store (BE-03 makes False)."""
        return False

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


# ---------------------------------------------------------------------------
# Token format helpers
# ---------------------------------------------------------------------------

TOKEN_NAMESPACE: str = "vw"


def assemble_token(prefix: str, secret: str) -> str:
    """Build the on-the-wire token from (prefix, secret)."""
    return f"{TOKEN_NAMESPACE}_{prefix}_{secret}"


def parse_token(raw: str) -> tuple[str, str] | None:
    """Parse ``vw_<prefix>_<secret>``. Return ``None`` on malformed input.

    The prefix and secret must each meet their minimum lengths
    (``TOKEN_PREFIX_LEN``, ``TOKEN_SECRET_LEN``). This rejects
    obviously-short candidates like ``vw_only_one`` without ever
    touching the store.
    """
    if not isinstance(raw, str):
        return None
    parts = raw.split("_", 2)
    if len(parts) != 3:
        return None
    namespace, prefix, secret = parts
    if namespace != TOKEN_NAMESPACE:
        return None
    if len(prefix) < TOKEN_PREFIX_LEN or len(secret) < TOKEN_SECRET_LEN:
        return None
    return prefix, secret


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ApiKeyStore(Protocol):
    """Persistence boundary for API keys.

    Implementations:

    - :class:`InMemoryApiKeyStore` — ships today; tests and dev/test
      runtime use it.
    - Postgres-backed — BE-03 adds it; queries
      ``vw_admin.api_keys WHERE prefix = $1 AND revoked_at IS NULL``,
      then verifies the secret.
    - :class:`RedisCachedApiKeyStore` — wraps any other store; BE-02b
      (Redis dep) wires the actual cache.
    """

    async def lookup_by_token(self, raw_token: str) -> ApiKey | None:
        """Resolve a wire token to an :class:`ApiKey`. Touches ``last_used_at``.

        Returns ``None`` if the token is malformed, unknown, the secret
        does not verify, or the key is revoked. Never raises.
        """
        ...

    async def issue(
        self,
        tenant_id: str,
        label: str | None = None,
        scopes: tuple[str, ...] = ("query",),
    ) -> tuple[ApiKey, str]:
        """Issue a new key. Returns (model, raw_token) — raw shown once."""
        ...

    async def revoke(self, key_id: str) -> ApiKey | None:
        """Revoke a key. Returns the updated row, or ``None`` if absent."""
        ...

    async def list_for_tenant(self, tenant_id: str) -> list[ApiKey]:
        """List all keys for a tenant (including revoked, for the audit trail)."""
        ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------

@dataclass
class _StoredRecord:
    """Internal row. Holds the hash that ``ApiKey`` never carries."""

    key: ApiKey
    key_hash: str


class InMemoryApiKeyStore:
    """In-process store. Thread-/coroutine-safe via an asyncio Lock.

    Replaced by a Postgres-backed implementation in BE-03. The contract
    matches :class:`ApiKeyStore` exactly so the swap is body-only.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, _StoredRecord] = {}
        self._by_prefix: dict[str, _StoredRecord] = {}
        self._lock = asyncio.Lock()

    async def issue(
        self,
        tenant_id: str,
        label: str | None = None,
        scopes: tuple[str, ...] = ("query",),
    ) -> tuple[ApiKey, str]:
        prefix, secret = generate_token_parts()
        async with self._lock:
            # Practically zero collision risk on 12 random url-safe chars,
            # but be paranoid for the in-memory case.
            while prefix in self._by_prefix:
                prefix, secret = generate_token_parts()
            now = datetime.now(timezone.utc)
            model = ApiKey(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                prefix=prefix,
                label=label,
                created_at=now,
                last_used_at=None,
                revoked_at=None,
                scopes=tuple(scopes),
            )
            record = _StoredRecord(key=model, key_hash=hash_token(secret))
            self._by_id[model.id] = record
            self._by_prefix[prefix] = record
        raw_token = assemble_token(prefix, secret)
        return model, raw_token

    async def lookup_by_token(self, raw_token: str) -> ApiKey | None:
        parsed = parse_token(raw_token)
        if parsed is None:
            return None
        prefix, secret = parsed
        record = self._by_prefix.get(prefix)
        if record is None:
            return None
        if record.key.revoked_at is not None:
            return None
        if not verify_token(secret, record.key_hash):
            return None
        # Touch last_used_at (non-atomic by design; the real Postgres
        # impl will do this in a single statement).
        async with self._lock:
            updated = record.key.model_copy(
                update={"last_used_at": datetime.now(timezone.utc)},
            )
            record.key = updated
        return record.key

    async def revoke(self, key_id: str) -> ApiKey | None:
        async with self._lock:
            record = self._by_id.get(key_id)
            if record is None:
                return None
            if record.key.revoked_at is not None:
                return record.key
            updated = record.key.model_copy(
                update={"revoked_at": datetime.now(timezone.utc)},
            )
            record.key = updated
            return updated

    async def list_for_tenant(self, tenant_id: str) -> list[ApiKey]:
        return [
            r.key
            for r in self._by_id.values()
            if r.key.tenant_id == tenant_id
        ]


# ---------------------------------------------------------------------------
# Redis cache wrapper (interface today; Redis client lands in BE-02b)
# ---------------------------------------------------------------------------

class RedisCachedApiKeyStore:
    """Wraps another :class:`ApiKeyStore` with a short-TTL cache.

    Today this is a pass-through: the Redis dependency is intentionally
    a stub per the M1-BE-02 ticket. The wrapper exists so the API
    layer's call sites are stable — when BE-02b wires Redis, only this
    file changes.

    Cache semantics (when wired):

    - ``lookup_by_token`` caches positive results for ~30s keyed by
      ``hash(raw_token)`` (never the raw token).
    - ``revoke`` invalidates the cache entry for the matching prefix.
    - ``issue`` does not pre-populate the cache (new tokens see one
      cache miss on first use; that's fine).
    """

    def __init__(self, inner: ApiKeyStore, *, redis_client: Any | None = None) -> None:
        self._inner = inner
        self._redis = redis_client  # stub; remains None in M1-BE-02

    async def lookup_by_token(self, raw_token: str) -> ApiKey | None:
        # TODO(BE-02b): consult Redis first. Today, pass-through.
        return await self._inner.lookup_by_token(raw_token)

    async def issue(
        self,
        tenant_id: str,
        label: str | None = None,
        scopes: tuple[str, ...] = ("query",),
    ) -> tuple[ApiKey, str]:
        return await self._inner.issue(tenant_id, label=label, scopes=scopes)

    async def revoke(self, key_id: str) -> ApiKey | None:
        # TODO(BE-02b): invalidate cache entries pointing at this key's prefix.
        return await self._inner.revoke(key_id)

    async def list_for_tenant(self, tenant_id: str) -> list[ApiKey]:
        return await self._inner.list_for_tenant(tenant_id)


__all__ = [
    "ApiKey",
    "ApiKeyStore",
    "InMemoryApiKeyStore",
    "RedisCachedApiKeyStore",
    "TOKEN_NAMESPACE",
    "assemble_token",
    "parse_token",
]

"""Auth package: API-key issuance, validation, hashing, FastAPI deps.

Modules:
- :mod:`hashing` — argon2 token hash + verify (with stdlib fallback flagged).
- :mod:`keys` — ``ApiKey`` Pydantic model + ``ApiKeyStore`` protocol +
  in-memory implementation (real Postgres impl waits for BE-03).
- :mod:`middleware` — FastAPI dependency ``api_key_required`` and
  ``admin_key_required`` that ``deps.py`` re-exports.

BE-03 will swap the in-memory store for the Postgres-backed one and
wire the Redis-cached wrapper. The public surface stays the same.
"""

from __future__ import annotations

from .keys import ApiKey, ApiKeyStore, InMemoryApiKeyStore, RedisCachedApiKeyStore
from .middleware import (
    admin_key_required,
    api_key_required,
    get_api_key_store,
    set_api_key_store,
)

__all__ = [
    "ApiKey",
    "ApiKeyStore",
    "InMemoryApiKeyStore",
    "RedisCachedApiKeyStore",
    "admin_key_required",
    "api_key_required",
    "get_api_key_store",
    "set_api_key_store",
]

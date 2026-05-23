"""Pytest fixtures.

Each test gets a fresh FastAPI app bound to a ``Settings(env='test')``
instance, with a ``TestClient`` for synchronous calls and an
``httpx.AsyncClient`` for async calls. ``get_settings``'s lru_cache is
cleared between tests so env-var overrides actually take effect.

BE-02 swapped the auth dep from a "any-bearer-token-accepted" stub to
a real argon2-verified one. The ``admin_auth_headers`` fixture now
issues a real admin key from the app's in-memory store; legacy tests
that previously sent ``Bearer vw_test_stub_admin_key`` get a real key
transparently.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from versawiki_api.app import create_app
from versawiki_api.auth.keys import InMemoryApiKeyStore, RedisCachedApiKeyStore
from versawiki_api.config import Settings, get_settings


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(env="test", log_level="WARNING")


@pytest.fixture
def api_key_store() -> RedisCachedApiKeyStore:
    """Fresh in-memory store wrapped in the (stub) Redis-cache wrapper."""
    return RedisCachedApiKeyStore(InMemoryApiKeyStore())


@pytest.fixture
def app(settings: Settings, api_key_store: RedisCachedApiKeyStore) -> FastAPI:
    return create_app(settings, api_key_store=api_key_store)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _run(coro):
    """Run an awaitable to completion on a fresh event loop.

    Used by sync fixtures that need to call into the async store. We
    create a one-shot loop rather than reusing ``asyncio.get_event_loop``
    (deprecated when there's no running loop on 3.12+) and we close it
    immediately so subsequent fixtures get a clean slate.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def admin_auth_headers(
    api_key_store: RedisCachedApiKeyStore,
) -> dict[str, str]:
    """A header dict carrying a freshly-issued admin key for this test's app.

    The fixture relies on the same ``api_key_store`` fixture instance
    that ``app`` is built with, so ``api_key_required`` on every route
    will resolve the token successfully.
    """
    _, raw_token = _run(
        api_key_store.issue(
            tenant_id="stub-tenant-id",
            label="test-admin",
            scopes=("query", "admin"),
        ),
    )
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.fixture
def query_auth_headers(
    api_key_store: RedisCachedApiKeyStore,
) -> dict[str, str]:
    """A header dict carrying a query-only key for negative-scope tests."""
    _, raw_token = _run(
        api_key_store.issue(
            tenant_id="stub-tenant-id",
            label="test-query",
            scopes=("query",),
        ),
    )
    return {"Authorization": f"Bearer {raw_token}"}

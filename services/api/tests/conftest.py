"""Pytest fixtures.

Each test gets a fresh FastAPI app bound to a ``Settings(env='test')``
instance, with a ``TestClient`` for synchronous calls and an
``httpx.AsyncClient`` for async calls. ``get_settings``'s lru_cache is
cleared between tests so env-var overrides actually take effect.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from versawiki_api.app import create_app
from versawiki_api.config import Settings, get_settings


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(env="test", log_level="WARNING")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def admin_auth_headers() -> dict[str, str]:
    """Bearer token accepted by the stub api_key_required in test env."""
    return {"Authorization": "Bearer vw_test_stub_admin_key"}

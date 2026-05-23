"""Async SQLAlchemy engine + session factory.

This module is the single seam between the rest of the API process and
Postgres. Three layers:

1. :func:`get_async_engine` — builds (and process-caches) an
   :class:`AsyncEngine` from a :class:`Settings`. The engine owns the
   connection pool.
2. :func:`async_session_factory` — turns an engine into an
   ``async_sessionmaker`` bound to ``AsyncSession``.
3. :func:`get_session` — FastAPI dependency that yields a fresh
   :class:`AsyncSession` per request and closes it on exit.

The engine is cached per (process, database URL) because creating a
pool per request would be a foot-cannon. Tests that need a clean
engine clear the cache via :func:`reset_engine_cache`.

The engine factory uses driver ``asyncpg`` by default — the
:attr:`Settings.database_url` is expected to be
``postgresql+asyncpg://...``. The legacy sync DSN on
:attr:`Settings.db_url` is *not* consulted here; it remains so any
pre-BE-03 caller that imported it still builds, but it is dead weight
for the data layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import Settings, get_settings
from ..logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Engine cache
# ---------------------------------------------------------------------------

_ENGINE_CACHE: dict[str, AsyncEngine] = {}


def get_async_engine(settings: Settings) -> AsyncEngine:
    """Return a process-cached :class:`AsyncEngine` for these settings.

    Keyed on the database URL so a test that swaps the DSN gets a fresh
    pool. The pool size + overflow come from ``Settings``.
    """
    key = settings.database_url
    cached = _ENGINE_CACHE.get(key)
    if cached is not None:
        return cached

    engine = create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_pre_ping=True,
        future=True,
    )
    _ENGINE_CACHE[key] = engine
    log.info(
        "db_engine_created",
        url=_safe_url(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
    )
    return engine


def _safe_url(url: str) -> str:
    """Strip the password from a DSN for logging."""
    try:
        scheme_split = url.split("://", 1)
        if len(scheme_split) != 2:
            return url
        scheme, rest = scheme_split
        if "@" not in rest:
            return url
        creds, host = rest.rsplit("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return f"{scheme}://{creds}@{host}"
    except Exception:  # noqa: BLE001 — never let logging break a request
        return "(redacted)"


async def reset_engine_cache() -> None:
    """Dispose and clear every cached engine. For tests."""
    for engine in list(_ENGINE_CACHE.values()):
        await engine.dispose()
    _ENGINE_CACHE.clear()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an ``async_sessionmaker`` bound to the given engine.

    ``expire_on_commit=False`` so ORM instances stay usable after the
    enclosing transaction commits — this matches the FastAPI per-request
    lifecycle where the route handler often returns ORM rows that are
    then serialized by Pydantic *after* the session has closed.
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# ---------------------------------------------------------------------------
# FastAPI dep
# ---------------------------------------------------------------------------

def _settings_from_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a per-request :class:`AsyncSession` bound to the app's engine.

    On exit, the session is closed. We don't wrap the route in an
    auto-commit transaction here — handlers that need a transaction
    call ``async with session.begin()`` explicitly. That keeps the
    contract honest: a route that does no writes does no commits.
    """
    settings = _settings_from_request(request)
    engine = get_async_engine(settings)
    factory = async_session_factory(engine)
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


__all__ = [
    "AsyncEngine",
    "AsyncSession",
    "SessionDep",
    "async_session_factory",
    "get_async_engine",
    "get_session",
    "reset_engine_cache",
]

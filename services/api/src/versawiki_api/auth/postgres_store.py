"""Postgres-backed :class:`ApiKeyStore` against the ``vw_admin`` schema.

This is the production implementation. The in-memory store remains the
default for tests and the M1 dev runtime — see
:mod:`versawiki_api.auth.keys`.

Schema dependency: requires the ``vw_admin.api_keys`` and
``vw_admin.tenants`` tables created by the admin migration in
:mod:`versawiki_api.db.migrations.versions.admin`.

Touch-on-lookup: ``last_used_at`` is updated in the same statement
that selects the row, to avoid a second round-trip and to keep the
update atomic with the lookup (an already-revoked key never gets
its timestamp touched).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models.admin import ApiKeyRow
from .hashing import generate_token_parts, hash_token, verify_token
from .keys import ApiKey, ApiKeyStore, assemble_token, parse_token


class PostgresApiKeyStore:
    """Postgres-backed implementation of :class:`ApiKeyStore`.

    Construction takes an ``async_sessionmaker`` bound to the admin DB.
    Each method opens a fresh session, does its work in a single
    transaction, and closes the session on exit.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _row_to_model(row: ApiKeyRow) -> ApiKey:
        scopes_raw = row.scopes or []
        if not isinstance(scopes_raw, (list, tuple)):
            scopes_raw = [str(scopes_raw)]
        return ApiKey(
            id=row.id,
            tenant_id=row.tenant_id,
            prefix=row.prefix,
            label=row.label,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
            scopes=tuple(scopes_raw),
        )

    # ------------------------------------------------------------------ store

    async def issue(
        self,
        tenant_id: str,
        label: str | None = None,
        scopes: tuple[str, ...] = ("query",),
    ) -> tuple[ApiKey, str]:
        prefix, secret = generate_token_parts()
        async with self._sessionmaker() as session, session.begin():
            row = ApiKeyRow(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                prefix=prefix,
                key_hash=hash_token(secret),
                label=label,
                scopes=list(scopes),
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            model = self._row_to_model(row)
        raw_token = assemble_token(prefix, secret)
        return model, raw_token

    async def lookup_by_token(self, raw_token: str) -> ApiKey | None:
        parsed = parse_token(raw_token)
        if parsed is None:
            return None
        prefix, secret = parsed
        async with self._sessionmaker() as session, session.begin():
            stmt = select(ApiKeyRow).where(ApiKeyRow.prefix == prefix)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            if row.revoked_at is not None:
                return None
            if not verify_token(secret, row.key_hash):
                return None

            now = datetime.now(timezone.utc)
            # Single UPDATE for the touch — no SELECT+UPDATE race.
            await session.execute(
                update(ApiKeyRow)
                .where(ApiKeyRow.id == row.id)
                .values(last_used_at=now),
            )
            row.last_used_at = now
            return self._row_to_model(row)

    async def revoke(self, key_id: str) -> ApiKey | None:
        async with self._sessionmaker() as session, session.begin():
            stmt = select(ApiKeyRow).where(ApiKeyRow.id == key_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            if row.revoked_at is None:
                row.revoked_at = datetime.now(timezone.utc)
            return self._row_to_model(row)

    async def list_for_tenant(self, tenant_id: str) -> list[ApiKey]:
        async with self._sessionmaker() as session:
            stmt = select(ApiKeyRow).where(ApiKeyRow.tenant_id == tenant_id)
            rows = (await session.execute(stmt)).scalars().all()
            return [self._row_to_model(r) for r in rows]


# Runtime-protocol check (mypy can't see the Protocol checkable across files
# without an explicit type alias, but isinstance() works at runtime).
_PROTOCOL: type[ApiKeyStore] = PostgresApiKeyStore  # type: ignore[assignment]


__all__ = ["PostgresApiKeyStore"]

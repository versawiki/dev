"""End-to-end provisioner tests against a real Postgres.

These tests are marked ``@pytest.mark.integration`` and **skipped** if
``VW_TEST_DATABASE_URL`` is not set. Pointing them at a real Postgres
(e.g. via ``docker run --rm -p 5432:5432 -e POSTGRES_PASSWORD=test
postgres:16``) exercises the provisioner end-to-end:

- The ``CREATE SCHEMA`` actually creates a schema.
- The ``CREATE ROLE`` actually creates a role.
- The Alembic migration runs and creates the five stub tables.
- The per-tenant role can SELECT from its own schema only (negative
  test against another schema).
- The admin migration is independently runnable for the admin schema.

These tests are deliberately destructive (they CREATE / DROP schemas)
so they must be pointed at a disposable DB.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("VW_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("VW_TEST_DATABASE_URL not set; skipping integration tests.")
    return url


@pytest.fixture(scope="module")
def settings(database_url: str):
    from versawiki_api.config import Settings

    return Settings(env="test", database_url=database_url, log_level="WARNING")


@pytest.fixture(scope="module")
async def engine(settings):
    from versawiki_api.db.engine import get_async_engine, reset_engine_cache

    eng = get_async_engine(settings)
    yield eng
    await reset_engine_cache()


@pytest.fixture(scope="module")
async def admin_migrations_applied(engine, settings):
    """Apply the admin migration once per module."""
    import subprocess
    import sys
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2]
    alembic_ini = api_root / "alembic.ini"

    env = dict(os.environ)
    env["VW_MIGRATION_TARGET"] = "admin"
    env["VW_DATABASE_URL"] = settings.database_url.replace(
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
    )
    env["PYTHONPATH"] = str(api_root / "src") + os.pathsep + env.get("PYTHONPATH", "")

    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "admin migration failed:\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}",
        )
    return True


@pytest.mark.asyncio
async def test_provisioner_creates_schema_and_role(
    engine,
    settings,
    admin_migrations_applied,
) -> None:
    from sqlalchemy import text

    from versawiki_api.db.provisioner import TenantProvisioner

    slug = f"itest{uuid.uuid4().hex[:8]}"
    provisioner = TenantProvisioner(engine, settings)
    result = await provisioner.provision(slug)

    assert result.schema == f"vw_{slug}"
    assert result.role == f"vw_{slug}_app"
    assert result.role_password

    async with engine.connect() as conn:
        # Schema exists.
        row = (await conn.execute(
            text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = :s"),
            {"s": result.schema},
        )).first()
        assert row is not None

        # Role exists.
        role_row = (await conn.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = :r"),
            {"r": result.role},
        )).first()
        assert role_row is not None

        # All five stub tables exist in the new schema.
        tables = (await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :s ORDER BY table_name",
            ),
            {"s": result.schema},
        )).all()
        names = {t[0] for t in tables}
        expected = {"documents", "chunks", "pages", "ontology_nodes", "query_log"}
        assert expected <= names

    # Cleanup.
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{result.schema}" CASCADE'))
        await conn.execute(text(f'DROP ROLE "{result.role}"'))


@pytest.mark.asyncio
async def test_tenant_role_cannot_see_other_tenant_schema(
    engine,
    settings,
    admin_migrations_applied,
) -> None:
    """Belt-and-braces isolation: role A cannot access schema B."""
    from sqlalchemy import text

    from versawiki_api.db.provisioner import TenantProvisioner

    provisioner = TenantProvisioner(engine, settings)
    slug_a = f"isoa{uuid.uuid4().hex[:8]}"
    slug_b = f"isob{uuid.uuid4().hex[:8]}"
    result_a = await provisioner.provision(slug_a)
    result_b = await provisioner.provision(slug_b)

    # Tenant A's role only has USAGE+CREATE on schema A; it has no
    # privilege on schema B. Verify by checking the explicit grant
    # tables.
    async with engine.connect() as conn:
        rows = (await conn.execute(
            text(
                "SELECT has_schema_privilege(:role, :schema, 'USAGE') AS has_usage",
            ),
            {"role": result_a.role, "schema": result_b.schema},
        )).all()
        assert rows[0][0] is False

    # Cleanup.
    async with engine.begin() as conn:
        for r in (result_a, result_b):
            await conn.execute(text(f'DROP SCHEMA "{r.schema}" CASCADE'))
            await conn.execute(text(f'DROP ROLE "{r.role}"'))

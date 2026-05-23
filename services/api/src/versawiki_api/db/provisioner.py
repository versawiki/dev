"""Per-tenant schema + role provisioner.

What "provisioning a tenant" means here:

1. Validate the slug. The slug is spliced into a Postgres identifier
   and a role name; we reject anything that isn't lowercase
   ``[a-z][a-z0-9-]{1,30}[a-z0-9]``. Anything that survives gets
   wrapped in :class:`sqlalchemy.sql.quoted_name` for extra
   belt-and-braces; we never use ``f"... {slug} ..."`` in raw SQL.
2. ``CREATE SCHEMA "vw_<slug>"``.
3. ``CREATE ROLE "vw_<slug>_app" WITH LOGIN PASSWORD '...'`` — the
   password is generated here, returned to the caller exactly once
   (so the admin endpoint can surface it), and then forgotten.
4. ``GRANT USAGE, CREATE ON SCHEMA "vw_<slug>" TO "vw_<slug>_app"``.
5. Run the per-tenant Alembic migration with
   ``VW_TENANT_SCHEMA=vw_<slug>`` set, which stamps the five stub
   tables defined in :mod:`versawiki_api.db.models.tenant` into the
   new schema and grants table-level privileges to the role.

This module is thin on purpose: it owns the SQL flow but delegates
the per-tenant table creation to Alembic so there is exactly one
source of truth for the per-tenant schema (the migrations under
``db/migrations/versions/tenant/``).

The class exposes :meth:`render_provision_sql` so unit tests can
assert the SQL flow without touching Postgres.
"""

from __future__ import annotations

import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import dialect as pg_dialect
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.elements import quoted_name

from ..config import Settings
from ..logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

# Match the rules in schemas/tenant.py *and* the BE-03 ticket spec
# (lowercase alphanumeric + dash, length 3-32, must start with a
# letter). The schemas regex permits up to 40 chars; we tighten to 32
# at the provisioner boundary because the role name = ``vw_<slug>_app``
# must fit inside Postgres's 63-byte NAMEDATALEN.
_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")


class InvalidSlugError(ValueError):
    """Raised when a slug doesn't pass the strict provisioner regex."""


def validate_slug(slug: str) -> str:
    """Return the slug if valid; raise :class:`InvalidSlugError` otherwise."""
    if not isinstance(slug, str):
        raise InvalidSlugError("Slug must be a string.")
    if not _SLUG_PATTERN.match(slug):
        raise InvalidSlugError(
            "Slug must match ^[a-z][a-z0-9-]{1,30}[a-z0-9]$ "
            "(lowercase letters, digits, hyphens; start with a letter; 3-32 chars).",
        )
    if "--" in slug:
        raise InvalidSlugError("Slug must not contain consecutive hyphens.")
    return slug


def schema_name_for(slug: str) -> str:
    """Return the per-tenant schema name (``vw_<slug>``)."""
    return f"vw_{validate_slug(slug)}"


def role_name_for(slug: str) -> str:
    """Return the per-tenant Postgres role name (``vw_<slug>_app``)."""
    return f"vw_{validate_slug(slug)}_app"


# ---------------------------------------------------------------------------
# SQL rendering
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProvisionPlan:
    """The set of statements the provisioner will execute, plus metadata.

    Exposed so unit tests can assert the SQL shape without running
    against a real Postgres. ``role_password`` is generated fresh
    every call.
    """

    slug: str
    schema: str
    role: str
    role_password: str
    statements: tuple[str, ...]


def _quote(identifier: str) -> str:
    """Render a Postgres identifier with paranoid double-quoting.

    We use :class:`sqlalchemy.sql.elements.quoted_name` (which the
    dialect honors) plus an explicit assertion that the identifier
    matches our allow-list. Belt and braces: if a future caller bypasses
    :func:`validate_slug`, this still refuses to render anything weird.
    """
    if not re.match(r"^[a-z][a-z0-9_]*$", identifier) and not re.match(
        r"^vw_[a-z0-9-]+(_app)?$",
        identifier,
    ):
        raise InvalidSlugError(f"Refusing to quote suspicious identifier: {identifier!r}")
    qn = quoted_name(identifier, quote=True)
    # quoted_name carries a flag; pg dialect renders it as "..."
    return pg_dialect().identifier_preparer.quote(qn)


def _generate_role_password(byte_count: int = 32) -> str:
    """Generate a URL-safe random password for a per-tenant role."""
    return secrets.token_urlsafe(byte_count)


def _escape_sql_string(value: str) -> str:
    """Escape a Postgres string literal (double single-quotes).

    We only use this for the role password, which is a token_urlsafe
    string (no single quotes), but be paranoid anyway.
    """
    return value.replace("'", "''")


def build_provision_plan(slug: str, *, role_password: str | None = None) -> ProvisionPlan:
    """Build the (idempotent-friendly) provisioning plan for a slug.

    Returns the rendered SQL strings the provisioner will execute. The
    statements are in execution order:

    1. ``CREATE SCHEMA "vw_<slug>"``
    2. ``CREATE ROLE "vw_<slug>_app" WITH LOGIN PASSWORD '...'``
    3. ``GRANT USAGE, CREATE ON SCHEMA "vw_<slug>" TO "vw_<slug>_app"``
    4. ``ALTER DEFAULT PRIVILEGES`` so future tables grant SELECT/INSERT/
       UPDATE/DELETE to the role by default. (Alembic creates the
       tables in the next step; this grant ensures the role can use
       them.)
    """
    validate_slug(slug)
    schema = schema_name_for(slug)
    role = role_name_for(slug)
    password = role_password if role_password is not None else _generate_role_password()
    escaped_password = _escape_sql_string(password)

    quoted_schema = _quote(schema)
    quoted_role = _quote(role)

    statements = (
        f'CREATE SCHEMA {quoted_schema}',
        f"CREATE ROLE {quoted_role} WITH LOGIN PASSWORD '{escaped_password}'",
        f'GRANT USAGE, CREATE ON SCHEMA {quoted_schema} TO {quoted_role}',
        (
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA {quoted_schema} '
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_role}'
        ),
        (
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA {quoted_schema} '
            f'GRANT USAGE, SELECT ON SEQUENCES TO {quoted_role}'
        ),
    )
    return ProvisionPlan(
        slug=slug,
        schema=schema,
        role=role,
        role_password=password,
        statements=statements,
    )


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProvisionResult:
    """What the provisioner returns to its caller (typically the admin route)."""

    schema: str
    role: str
    role_password: str  # show once, never again


class TenantProvisioner:
    """Provisions a per-tenant schema + role and runs the tenant migrations.

    Construction takes an :class:`AsyncEngine` (the admin-level engine
    with sufficient privileges — ``CREATE SCHEMA`` + ``CREATE ROLE``)
    and a :class:`Settings` for the migration subprocess.

    Idempotency: the provisioner does NOT swallow ``DuplicateSchema`` /
    ``DuplicateObject`` errors today. Callers are expected to check
    the admin ``tenants`` table first and 409 the request before
    calling :meth:`provision`. The ticket scope is "create new"; an
    "ensure" mode is a follow-up.
    """

    def __init__(self, engine: AsyncEngine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    async def provision(
        self,
        slug: str,
        *,
        role_password: str | None = None,
    ) -> ProvisionResult:
        """Provision a tenant. Returns metadata including the role password.

        The password is returned exactly once — store it in the
        response body (or a sealed admin notification) and forget it.
        """
        plan = build_provision_plan(slug, role_password=role_password)
        async with self._engine.begin() as conn:
            for stmt in plan.statements:
                # Each DDL statement runs in autocommit-equivalent
                # via the AsyncEngine.begin() transaction; Postgres
                # supports transactional DDL.
                await conn.execute(text(stmt))

        # Now run per-tenant migrations against the new schema. We
        # invoke Alembic in a subprocess so we don't have to deal with
        # async-event-loop reentrancy (Alembic is sync-only inside
        # ``upgrade`` and creates its own engine).
        self._run_tenant_migrations(plan.schema)

        log.info(
            "tenant_provisioned",
            slug=plan.slug,
            schema=plan.schema,
            role=plan.role,
        )
        return ProvisionResult(
            schema=plan.schema,
            role=plan.role,
            role_password=plan.role_password,
        )

    def _run_tenant_migrations(self, schema: str) -> None:
        """Run ``alembic upgrade head`` against the new tenant schema.

        We invoke via ``subprocess.run([sys.executable, '-m', 'alembic', ...])``
        so the migration runs with the package's environment intact
        and so this method stays sync (the asyncpg event loop doesn't
        get tangled with Alembic's sync engine).
        """
        alembic_ini = _alembic_ini_path()
        env = _make_subprocess_env(
            target="tenant",
            tenant_schema=schema,
            database_url=self._settings.database_url,
        )
        cmd = [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"]
        completed = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "tenant migration failed:\n"
                f"  cmd: {' '.join(cmd)}\n"
                f"  stdout: {completed.stdout}\n"
                f"  stderr: {completed.stderr}",
            )


def _alembic_ini_path() -> Path:
    """Find ``alembic.ini`` packaged with the service.

    Looks up two parents from this file (db/ -> versawiki_api/ ->
    src/) and walks up one more to ``services/api/alembic.ini``.
    """
    here = Path(__file__).resolve()
    # .../services/api/src/versawiki_api/db/provisioner.py
    # parents[3] -> services/api
    return here.parents[3] / "alembic.ini"


def _make_subprocess_env(
    *,
    target: str,
    tenant_schema: str | None,
    database_url: str,
) -> dict[str, str]:
    """Build the environment dict for the Alembic subprocess.

    Alembic's ``env.py`` reads:

    - ``VW_MIGRATION_TARGET`` — ``admin`` or ``tenant``.
    - ``VW_TENANT_SCHEMA`` — required if target is ``tenant``.
    - ``VW_DATABASE_URL`` — sync DSN for Alembic's engine.
    """
    import os

    env = dict(os.environ)
    env["VW_MIGRATION_TARGET"] = target
    if tenant_schema is not None:
        env["VW_TENANT_SCHEMA"] = tenant_schema
    # Alembic's env.py uses a sync engine, so we rewrite the asyncpg
    # scheme to the psycopg sync driver if needed.
    env["VW_DATABASE_URL"] = _to_sync_dsn(database_url)
    # Make sure the package on PYTHONPATH so ``alembic -m`` finds the
    # ``env.py`` script_location.
    here = Path(__file__).resolve()
    src_dir = here.parents[2]  # services/api/src
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing}" if existing else str(src_dir)
    return env


def _to_sync_dsn(url: str) -> str:
    """Translate an asyncpg DSN to a psycopg one for Alembic."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://"):]
    return url


__all__ = [
    "InvalidSlugError",
    "ProvisionPlan",
    "ProvisionResult",
    "TenantProvisioner",
    "build_provision_plan",
    "role_name_for",
    "schema_name_for",
    "validate_slug",
]

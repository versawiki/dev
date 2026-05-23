"""Unit tests for the tenant provisioner — SQL rendering + slug rules.

These tests do not touch Postgres. They exercise:

- Slug validation (rejects malformed inputs).
- :func:`schema_name_for` / :func:`role_name_for` derive the right
  identifiers.
- :func:`build_provision_plan` renders the expected SQL flow:
  ``CREATE SCHEMA``, ``CREATE ROLE ... WITH LOGIN PASSWORD ...``,
  ``GRANT USAGE, CREATE ON SCHEMA ...``, plus the default-privileges
  grants for tables and sequences.
- Identifier quoting prevents SQL injection if a future caller
  bypasses :func:`validate_slug`.
"""

from __future__ import annotations

import pytest

from versawiki_api.db.provisioner import (
    InvalidSlugError,
    build_provision_plan,
    role_name_for,
    schema_name_for,
    validate_slug,
)


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "slug",
    [
        "acme",
        "acme-eng",
        "globex-1",
        "a1b",
        "alpha-beta-gamma",
    ],
)
def test_validate_slug_accepts_well_formed(slug: str) -> None:
    assert validate_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "ab",                  # too short (< 3)
        "1abc",                # starts with digit
        "-abc",                # starts with hyphen
        "abc-",                # ends with hyphen
        "ab--cd",              # consecutive hyphens
        "Acme",                # uppercase
        "abc_def",             # underscore
        "abc def",             # space
        "abc.def",             # dot
        "a" * 40,              # too long (> 32)
        'abc"; DROP TABLE x',  # SQL injection attempt
    ],
)
def test_validate_slug_rejects_malformed(slug: str) -> None:
    with pytest.raises(InvalidSlugError):
        validate_slug(slug)


def test_validate_slug_rejects_non_string() -> None:
    with pytest.raises(InvalidSlugError):
        validate_slug(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Derived names
# ---------------------------------------------------------------------------

def test_schema_and_role_names() -> None:
    assert schema_name_for("acme") == "vw_acme"
    assert role_name_for("acme") == "vw_acme_app"
    assert schema_name_for("acme-eng") == "vw_acme-eng"
    assert role_name_for("acme-eng") == "vw_acme-eng_app"


def test_schema_name_rejects_invalid_slug() -> None:
    with pytest.raises(InvalidSlugError):
        schema_name_for("Bad Slug")


# ---------------------------------------------------------------------------
# Plan rendering
# ---------------------------------------------------------------------------

def test_provision_plan_basic_shape() -> None:
    plan = build_provision_plan("acme", role_password="dummypassword")
    assert plan.slug == "acme"
    assert plan.schema == "vw_acme"
    assert plan.role == "vw_acme_app"
    assert plan.role_password == "dummypassword"
    assert len(plan.statements) == 5


def test_provision_plan_renders_create_schema_first() -> None:
    plan = build_provision_plan("acme", role_password="pw")
    assert plan.statements[0] == 'CREATE SCHEMA "vw_acme"'


def test_provision_plan_renders_create_role_with_password() -> None:
    plan = build_provision_plan("acme", role_password="hunter2")
    assert plan.statements[1] == 'CREATE ROLE "vw_acme_app" WITH LOGIN PASSWORD \'hunter2\''


def test_provision_plan_renders_grant_usage_create() -> None:
    plan = build_provision_plan("acme", role_password="pw")
    assert plan.statements[2] == (
        'GRANT USAGE, CREATE ON SCHEMA "vw_acme" TO "vw_acme_app"'
    )


def test_provision_plan_renders_default_privileges() -> None:
    plan = build_provision_plan("acme", role_password="pw")
    table_grant = plan.statements[3]
    sequence_grant = plan.statements[4]
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA \"vw_acme\"" in table_grant
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO \"vw_acme_app\"" in table_grant
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA \"vw_acme\"" in sequence_grant
    assert "GRANT USAGE, SELECT ON SEQUENCES TO \"vw_acme_app\"" in sequence_grant


def test_provision_plan_escapes_password_single_quotes() -> None:
    plan = build_provision_plan("acme", role_password="o'malley")
    # Password literal is single-quoted; embedded ' must be doubled.
    assert "WITH LOGIN PASSWORD 'o''malley'" in plan.statements[1]


def test_provision_plan_quotes_hyphenated_slug() -> None:
    plan = build_provision_plan("acme-eng", role_password="pw")
    assert plan.statements[0] == 'CREATE SCHEMA "vw_acme-eng"'
    assert plan.statements[1] == (
        'CREATE ROLE "vw_acme-eng_app" WITH LOGIN PASSWORD \'pw\''
    )
    assert '"vw_acme-eng"' in plan.statements[2]
    assert '"vw_acme-eng_app"' in plan.statements[2]


def test_provision_plan_generates_password_when_omitted() -> None:
    plan1 = build_provision_plan("acme")
    plan2 = build_provision_plan("acme")
    # Each call generates a fresh password.
    assert plan1.role_password != plan2.role_password
    assert len(plan1.role_password) >= 32


def test_provision_plan_rejects_invalid_slug() -> None:
    with pytest.raises(InvalidSlugError):
        build_provision_plan("Bad Slug")


# ---------------------------------------------------------------------------
# Defense in depth: identifier quoting
# ---------------------------------------------------------------------------

def test_no_unquoted_identifier_in_any_statement() -> None:
    """Every schema/role reference must be wrapped in double quotes."""
    plan = build_provision_plan("acme", role_password="pw")
    for stmt in plan.statements:
        # If "vw_acme" appears, it must be quoted.
        if "vw_acme" in stmt:
            assert '"vw_acme' in stmt or "'vw_acme" in stmt, stmt


def test_role_name_fits_postgres_namedatalen() -> None:
    # Postgres NAMEDATALEN default = 63. We use up at most:
    #   len("vw_") + 32 (slug max) + len("_app") = 39. Plenty of margin.
    plan = build_provision_plan("a" + "1" * 30 + "z", role_password="pw")
    assert len(plan.role) <= 63
    assert len(plan.schema) <= 63

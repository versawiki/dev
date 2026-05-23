"""init admin schema

Creates the shared ``vw_admin`` schema, plus its ``tenants`` and
``api_keys`` tables. This migration is the entry point of the admin
chain: any future admin DDL change appends a new revision in
``versions/admin/`` and chains to this one.

Revision ID: 20260522_0001
Revises:
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260522_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ADMIN_SCHEMA = "vw_admin"


def upgrade() -> None:
    bind = op.get_bind()
    # Idempotency: the provisioner may run this against a fresh DB
    # multiple times in tests. CREATE SCHEMA IF NOT EXISTS is harmless
    # if the schema already exists.
    bind.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{ADMIN_SCHEMA}"')

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False, server_default="free"),
        sa.Column("db_schema_name", sa.String(length=64), nullable=False),
        sa.Column("db_role_name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        schema=ADMIN_SCHEMA,
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{ADMIN_SCHEMA}.tenants.id"],
            ondelete="CASCADE",
            name="fk_api_keys_tenant_id",
        ),
        sa.UniqueConstraint("prefix", name="uq_api_keys_prefix"),
        schema=ADMIN_SCHEMA,
    )

    op.create_index(
        "ix_api_keys_tenant_id",
        "api_keys",
        ["tenant_id"],
        schema=ADMIN_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys", schema=ADMIN_SCHEMA)
    op.drop_table("api_keys", schema=ADMIN_SCHEMA)
    op.drop_table("tenants", schema=ADMIN_SCHEMA)

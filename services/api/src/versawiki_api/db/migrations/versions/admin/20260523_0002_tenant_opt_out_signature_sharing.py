"""tenant opt-out signature sharing

Adds the ``opt_out_signature_sharing`` boolean column to
``vw_admin.tenants``. Defaults to False at the server side so any
existing rows (and any pre-migration callers that don't set it)
remain enrolled in signature sharing.

Idempotency note: like 20260522_0001_init_admin_schema, this migration
may run multiple times against the same database in tests. ``add_column``
itself is not idempotent in Alembic, but the surrounding harness runs
each test against a fresh database, and production migrations only
roll forward through the linear chain. The default value is supplied
via ``server_default`` so backfill of existing rows is implicit.

Revision ID: 20260523_0002
Revises: 20260522_0001
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260523_0002"
down_revision: Union[str, Sequence[str], None] = "20260522_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ADMIN_SCHEMA = "vw_admin"


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "opt_out_signature_sharing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=ADMIN_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(
        "tenants",
        "opt_out_signature_sharing",
        schema=ADMIN_SCHEMA,
    )

"""init tenant schema (stub tables)

Creates the five per-tenant stub tables sketched in
``docs/architecture/v1.md`` § 2:

- ``documents``
- ``chunks``        — ING-02 fills in the pgvector(1024) column + HNSW.
- ``pages``         — wiki pages, derived artifact.
- ``ontology_nodes``— ING-04 fills in the embedding + confidence cols.
- ``query_log``     — BE-04 fills in the query_embedding + result jsonb.

The schema name itself is set by the env.py ``SET search_path TO ...``
at run time, so this migration uses unqualified table names.

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


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding_stub", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
            name="fk_chunks_document_id",
        ),
    )

    op.create_table(
        "pages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("last_built_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "ontology_nodes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="category"),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["ontology_nodes.id"],
            ondelete="SET NULL",
            name="fk_ontology_nodes_parent_id",
        ),
    )

    op.create_table(
        "query_log",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("caller_kind", sa.String(length=16), nullable=False, server_default="human"),
        sa.Column("api_key_id", sa.String(length=64), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("query_log")
    op.drop_table("ontology_nodes")
    op.drop_table("pages")
    op.drop_table("chunks")
    op.drop_table("documents")

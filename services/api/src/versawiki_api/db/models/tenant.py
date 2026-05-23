"""Declarative models for the per-tenant schemas.

There is **one schema per tenant** (``vw_<slug>``). The classes here
are templates: the same table shape applies inside every tenant
schema. At migration time, Alembic's env.py reads
``VW_TENANT_SCHEMA`` and stamps these tables into that schema.

The columns here are intentionally minimal stubs. The downstream
ingestion tickets fill in real columns:

- ``M1-ING-02`` — chunks + embedding columns + HNSW index.
- ``M1-ING-04`` — ontology nodes + document-ontology join table.
- ``M1-BE-04`` — query log enrichment for the re-indexing loop.

For now we ship the five tables sketched in the architecture doc
with just enough columns to (a) run a migration against a fresh
schema, (b) let the provisioner verify the tables exist, and (c)
serve as a target_metadata for autogenerate when ING tickets
expand them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, MetaData, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TenantBase(DeclarativeBase):
    """Base for every per-tenant table.

    Note: we deliberately do NOT bind a schema in the MetaData. The
    schema name is supplied at migration time via Alembic's
    ``version_table_schema`` / ``include_schemas`` plumbing in
    :mod:`versawiki_api.db.migrations.env`. That lets the same model
    classes be reused across hundreds of per-tenant schemas without
    one global ``ALTER`` ever touching another tenant's data.
    """

    metadata = MetaData()


class Document(TenantBase):
    """A document the ingestion pipeline has discovered."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # ING-02 fills in the rest (blob_key, last_modified_at, deleted_at, ...).


class Chunk(TenantBase):
    """A chunk of a document, ready for embedding + retrieval.

    The ``embedding`` column lives here in the real schema (vector(1024),
    HNSW indexed). ING-02 owns that migration. The stub column is
    JSON-typed so the table is creatable on any Postgres, including
    a local pgvector-less dev DB.
    """

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Placeholder. ING-02 swaps to pgvector(1024) + HNSW index.
    embedding_stub: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class WikiPage(TenantBase):
    """A wiki page — a derived artifact, not a source-of-truth row."""

    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_built_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OntologyNode(TenantBase):
    """A node in the induced ontology tree."""

    __tablename__ = "ontology_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("ontology_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="category")
    # ING-04 expands: embedding(1024), confidence, source (induced|meta-skill|human).


class QueryLog(TenantBase):
    """One row per resolved query. Drives the re-indexing loop."""

    __tablename__ = "query_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    caller_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="human")
    api_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # BE-04 fills query_embedding + result_chunk_ids jsonb.


__all__ = [
    "TenantBase",
    "Document",
    "Chunk",
    "WikiPage",
    "OntologyNode",
    "QueryLog",
]

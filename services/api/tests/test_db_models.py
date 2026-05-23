"""Shape tests for the SQLAlchemy declarative models.

These tests do not touch a real Postgres. They assert the table
definitions match what the architecture document and the BE-03
ticket spec require — schema name, table names, primary keys,
foreign keys, unique constraints, and the column lists.
"""

from __future__ import annotations

import pytest

from versawiki_api.db.models.admin import (
    ADMIN_SCHEMA,
    AdminBase,
    ApiKeyRow,
    Tenant,
)
from versawiki_api.db.models.tenant import (
    Chunk,
    Document,
    OntologyNode,
    QueryLog,
    TenantBase,
    WikiPage,
)


def test_admin_metadata_pinned_to_vw_admin_schema() -> None:
    assert AdminBase.metadata.schema == ADMIN_SCHEMA
    assert Tenant.__table__.schema == ADMIN_SCHEMA
    assert ApiKeyRow.__table__.schema == ADMIN_SCHEMA


def test_tenant_table_shape() -> None:
    cols = {c.name for c in Tenant.__table__.columns}
    assert {
        "id",
        "slug",
        "display_name",
        "plan",
        "db_schema_name",
        "db_role_name",
        "created_at",
    } <= cols
    # Primary key
    pk = {c.name for c in Tenant.__table__.primary_key.columns}
    assert pk == {"id"}
    # slug unique
    unique_constraint_names = {uc.name for uc in Tenant.__table__.constraints if uc.name}
    assert "uq_tenants_slug" in unique_constraint_names


def test_api_key_row_table_shape() -> None:
    cols = {c.name for c in ApiKeyRow.__table__.columns}
    assert {
        "id",
        "tenant_id",
        "prefix",
        "key_hash",
        "label",
        "scopes",
        "created_at",
        "last_used_at",
        "revoked_at",
    } <= cols
    # Foreign key to tenants.id
    fks = list(ApiKeyRow.__table__.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "tenants"
    assert fks[0].column.name == "id"
    assert fks[0].ondelete == "CASCADE"
    # prefix unique
    unique_constraint_names = {uc.name for uc in ApiKeyRow.__table__.constraints if uc.name}
    assert "uq_api_keys_prefix" in unique_constraint_names


def test_tenant_metadata_unscoped() -> None:
    # Per-tenant tables are NOT pinned to a schema at declaration time —
    # the schema is set at migration time via search_path.
    assert TenantBase.metadata.schema is None
    for model in (Document, Chunk, WikiPage, OntologyNode, QueryLog):
        assert model.__table__.schema is None


def test_tenant_table_names_match_ticket_spec() -> None:
    table_names = {t.name for t in TenantBase.metadata.tables.values()}
    assert table_names == {
        "documents",
        "chunks",
        "pages",
        "ontology_nodes",
        "query_log",
    }


@pytest.mark.parametrize(
    "model, expected_subset",
    [
        (Document, {"id", "source_uri", "content_hash", "title", "mime_type", "discovered_at"}),
        (Chunk, {"id", "document_id", "ordinal", "text", "token_count"}),
        (WikiPage, {"id", "slug", "title", "body_md", "body_html", "last_built_at"}),
        (OntologyNode, {"id", "parent_id", "label", "kind"}),
        (QueryLog, {"id", "caller_kind", "api_key_id", "query_text", "latency_ms", "created_at"}),
    ],
)
def test_tenant_models_have_expected_columns(model, expected_subset) -> None:
    cols = {c.name for c in model.__table__.columns}
    missing = expected_subset - cols
    assert not missing, f"{model.__name__} missing columns: {missing}"


def test_chunks_foreign_keys_documents() -> None:
    fks = list(Chunk.__table__.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "documents"
    assert fks[0].column.name == "id"
    assert fks[0].ondelete == "CASCADE"


def test_ontology_nodes_self_referential_fk() -> None:
    fks = list(OntologyNode.__table__.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "ontology_nodes"
    assert fks[0].ondelete == "SET NULL"

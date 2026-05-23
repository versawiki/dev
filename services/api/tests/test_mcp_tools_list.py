"""``tools/list`` returns the four cemented tool definitions.

The tool names + JSON Schemas are the public LLM-facing contract. We
assert:

1. Exactly four tools, names exactly ``search`` / ``read_page`` /
   ``read_chunk`` / ``list_ontology``.
2. Each tool's ``inputSchema`` validates cleanly under jsonschema's
   newest available validator (so an LLM client can rely on its
   tool-format-checker pass).
3. The required parameter for each tool is declared.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from versawiki_api.app import create_app
from versawiki_api.auth.keys import InMemoryApiKeyStore, RedisCachedApiKeyStore
from versawiki_api.config import Settings
from versawiki_api.db.tenant_store import InMemoryTenantStore, TenantRecord


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def tenant_store() -> InMemoryTenantStore:
    return InMemoryTenantStore()


@pytest.fixture
def seeded_tenant(tenant_store: InMemoryTenantStore) -> TenantRecord:
    return _run(
        tenant_store.create(
            slug="acme-eng",
            display_name="Acme Engineering",
            plan="free",
        ),
    )


@pytest.fixture
def app_with_tenant(
    settings: Settings,
    api_key_store: RedisCachedApiKeyStore,
    tenant_store: InMemoryTenantStore,
    seeded_tenant: TenantRecord,
) -> FastAPI:
    return create_app(
        settings,
        api_key_store=api_key_store,
        tenant_store=tenant_store,
    )


@pytest.fixture
def client(app_with_tenant: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_with_tenant) as test_client:
        yield test_client


@pytest.fixture
def tenant_headers(
    api_key_store: RedisCachedApiKeyStore,
    seeded_tenant: TenantRecord,
) -> dict[str, str]:
    _, raw = _run(
        api_key_store.issue(
            tenant_id=seeded_tenant.id,
            label="test-tenant",
            scopes=("query",),
        ),
    )
    return {"Authorization": f"Bearer {raw}"}


def _tools_list(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    response = client.post("/mcp", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["result"]["tools"]


def test_tools_list_returns_exactly_four_tools(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    tools = _tools_list(client, tenant_headers)
    assert isinstance(tools, list)
    names = sorted(t["name"] for t in tools)
    # Exact-name contract: LLM consumers hard-code these.
    assert names == ["list_ontology", "read_chunk", "read_page", "search"]


def test_tools_list_schemas_validate_cleanly(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    """Each tool's inputSchema must be a valid JSON Schema."""
    import jsonschema

    tools = _tools_list(client, tenant_headers)
    # Prefer the newest validator the installed jsonschema knows about.
    # Pydantic v2 emits Draft-2020-12-compatible schemas; older
    # jsonschema (< 4.x) only ships Draft 7, which is a strict subset
    # we're still well within. Pick whichever the runtime exposes.
    validator_cls = getattr(
        jsonschema,
        "Draft202012Validator",
        getattr(jsonschema, "Draft7Validator"),
    )
    for tool in tools:
        schema = tool["inputSchema"]
        validator_cls.check_schema(schema)


def test_search_schema_requires_q(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    tools = {t["name"]: t for t in _tools_list(client, tenant_headers)}
    schema = tools["search"]["inputSchema"]
    assert "q" in schema["properties"]
    assert "q" in schema["required"]


def test_read_page_schema_requires_page_id(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    tools = {t["name"]: t for t in _tools_list(client, tenant_headers)}
    schema = tools["read_page"]["inputSchema"]
    assert "page_id" in schema["properties"]
    assert "page_id" in schema["required"]


def test_read_chunk_schema_requires_chunk_id(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    tools = {t["name"]: t for t in _tools_list(client, tenant_headers)}
    schema = tools["read_chunk"]["inputSchema"]
    assert "chunk_id" in schema["properties"]
    assert "chunk_id" in schema["required"]


def test_list_ontology_schema_node_id_optional(
    client: TestClient,
    tenant_headers: dict[str, str],
) -> None:
    tools = {t["name"]: t for t in _tools_list(client, tenant_headers)}
    schema = tools["list_ontology"]["inputSchema"]
    assert "node_id" in schema["properties"]
    # node_id is optional — must NOT be in required.
    assert "node_id" not in schema.get("required", [])

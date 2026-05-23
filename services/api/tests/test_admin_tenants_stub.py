"""Shape tests for the /v1/admin/tenants stub.

These exist so client codegen against the OpenAPI spec is stable
even while persistence (BE-03) is unimplemented.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_create_tenant_stub_returns_shape_correct_body(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    payload = {"slug": "acme-eng", "display_name": "Acme Engineering", "plan": "free"}
    response = client.post("/v1/admin/tenants", json=payload, headers=admin_auth_headers)
    assert response.status_code == 201, response.text

    body = response.json()
    # Required keys
    for key in {"id", "slug", "display_name", "plan", "db_schema_name", "created_at"}:
        assert key in body, f"missing key: {key}"
    # Field-level shape
    assert body["slug"] == "acme-eng"
    assert body["display_name"] == "Acme Engineering"
    assert body["plan"] == "free"
    assert body["db_schema_name"] == "vw_acme-eng"
    # id is a UUID-shaped string
    uuid.UUID(body["id"])


def test_create_tenant_requires_authorization(client: TestClient) -> None:
    response = client.post(
        "/v1/admin/tenants",
        json={"slug": "acme", "display_name": "Acme", "plan": "free"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthenticated"


def test_create_tenant_rejects_invalid_slug(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/v1/admin/tenants",
        json={"slug": "-bad-", "display_name": "Bad", "plan": "free"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_list_tenants_returns_empty_page(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    response = client.get("/v1/admin/tenants", headers=admin_auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_get_tenant_returns_structured_404(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    response = client.get("/v1/admin/tenants/nonexistent", headers=admin_auth_headers)
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "tenant_not_found"
    assert body["error"]["details"]["tenant_id"] == "nonexistent"

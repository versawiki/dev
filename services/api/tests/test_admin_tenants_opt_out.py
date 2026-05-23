"""End-to-end tests for ``PATCH /v1/admin/tenants/{id}/opt-out``.

The route lets an operator set or clear the tenant's
``opt_out_signature_sharing`` flag. The meta-MCP collector honors
this via its own ``TenantSignatureConfig.opt_out``; here we only
test the API surface.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_tenant(
    client: TestClient,
    admin_auth_headers: dict[str, str],
    slug: str = "acme",
) -> str:
    response = client.post(
        "/v1/admin/tenants",
        json={"slug": slug, "display_name": slug.title(), "plan": "free"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Defaults to False at creation time.
    assert body["opt_out_signature_sharing"] is False
    return body["id"]


def test_patch_opt_out_true_returns_200_with_flag_set(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    tenant_id = _create_tenant(client, admin_auth_headers)
    response = client.patch(
        f"/v1/admin/tenants/{tenant_id}/opt-out",
        json={"opt_out_signature_sharing": True},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == tenant_id
    assert body["opt_out_signature_sharing"] is True
    # And a follow-up GET observes the same value.
    fetched = client.get(
        f"/v1/admin/tenants/{tenant_id}",
        headers=admin_auth_headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["opt_out_signature_sharing"] is True


def test_patch_opt_out_round_trip_back_to_false(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    tenant_id = _create_tenant(client, admin_auth_headers)
    # Opt out, then re-enroll.
    out = client.patch(
        f"/v1/admin/tenants/{tenant_id}/opt-out",
        json={"opt_out_signature_sharing": True},
        headers=admin_auth_headers,
    )
    assert out.status_code == 200
    assert out.json()["opt_out_signature_sharing"] is True

    back = client.patch(
        f"/v1/admin/tenants/{tenant_id}/opt-out",
        json={"opt_out_signature_sharing": False},
        headers=admin_auth_headers,
    )
    assert back.status_code == 200
    body = back.json()
    assert body["id"] == tenant_id
    assert body["opt_out_signature_sharing"] is False


def test_patch_opt_out_missing_tenant_returns_structured_404(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    response = client.patch(
        "/v1/admin/tenants/nonexistent-id/opt-out",
        json={"opt_out_signature_sharing": True},
        headers=admin_auth_headers,
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "tenant_not_found"
    assert body["error"]["details"]["tenant_id"] == "nonexistent-id"


def test_patch_opt_out_without_admin_auth_returns_401(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    # Create with auth, then PATCH without.
    tenant_id = _create_tenant(client, admin_auth_headers)
    response = client.patch(
        f"/v1/admin/tenants/{tenant_id}/opt-out",
        json={"opt_out_signature_sharing": True},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthenticated"


def test_patch_opt_out_with_extra_fields_returns_422(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    tenant_id = _create_tenant(client, admin_auth_headers)
    response = client.patch(
        f"/v1/admin/tenants/{tenant_id}/opt-out",
        json={"opt_out_signature_sharing": True, "rogue_field": "nope"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_patch_opt_out_with_missing_body_returns_422(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    tenant_id = _create_tenant(client, admin_auth_headers)
    response = client.patch(
        f"/v1/admin/tenants/{tenant_id}/opt-out",
        json={},
        headers=admin_auth_headers,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"

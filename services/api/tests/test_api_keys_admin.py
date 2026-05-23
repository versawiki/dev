"""Admin API for issuing, listing, and revoking tenant API keys.

Coverage (per M1-BE-02):

- Issue returns the raw token exactly once in the response.
- List never returns the raw token (or any hash); revoked keys appear
  with ``revoked_at`` populated so the audit trail is intact.
- Revoke flips a key to revoked; subsequent ``api_key_required``
  lookups for the same token fail (401).
- All endpoints require the ``admin`` scope: a query-only key is
  rejected with 403.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


TENANT = "stub-tenant-id"


def test_issue_api_key_returns_raw_token_once(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        json={"label": "web-app", "scopes": ["query"]},
        headers=admin_auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # Envelope keys
    assert set(body.keys()) == {"api_key", "token"}, body

    # The raw token is present, and only here.
    token = body["token"]
    assert isinstance(token, str)
    assert token.startswith("vw_")
    parts = token.split("_")
    assert len(parts) == 3, f"expected vw_<prefix>_<secret>, got {token}"
    assert parts[1] == body["api_key"]["prefix"]

    # api_key sub-object shape
    api_key = body["api_key"]
    for key in {
        "id",
        "tenant_id",
        "prefix",
        "label",
        "scopes",
        "created_at",
        "last_used_at",
        "revoked_at",
    }:
        assert key in api_key, f"missing key: {key}"
    assert api_key["tenant_id"] == TENANT
    assert api_key["label"] == "web-app"
    assert api_key["scopes"] == ["query"]
    assert api_key["revoked_at"] is None


def test_list_api_keys_never_returns_raw_token(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    # Issue two keys, then list.
    client.post(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        json={"label": "first"},
        headers=admin_auth_headers,
    )
    client.post(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        json={"label": "second"},
        headers=admin_auth_headers,
    )

    response = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The admin fixture's own key is also bound to TENANT, so we expect >= 3.
    assert body["total"] >= 3
    for item in body["items"]:
        # Wire model deliberately omits these:
        assert "token" not in item
        assert "key_hash" not in item
        assert "secret" not in item
        # And carries these:
        for key in {"id", "tenant_id", "prefix", "label", "scopes", "created_at"}:
            assert key in item


def test_revoke_api_key_blocks_subsequent_lookup(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    # Issue a fresh admin key so we can use it before revoking it.
    issue = client.post(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        json={"label": "doomed", "scopes": ["query", "admin"]},
        headers=admin_auth_headers,
    )
    assert issue.status_code == 201, issue.text
    body = issue.json()
    raw_token = body["token"]
    key_id = body["api_key"]["id"]
    issued_headers = {"Authorization": f"Bearer {raw_token}"}

    # Before revoke: the key works against an admin endpoint.
    before = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers=issued_headers,
    )
    assert before.status_code == 200, before.text

    # Revoke it.
    revoke = client.delete(
        f"/v1/admin/api-keys/{key_id}",
        headers=admin_auth_headers,
    )
    assert revoke.status_code == 200, revoke.text
    revoked = revoke.json()
    assert revoked["id"] == key_id
    assert revoked["revoked_at"] is not None

    # After revoke: same token now 401s.
    after = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers=issued_headers,
    )
    assert after.status_code == 401, after.text
    assert after.json()["error"]["code"] == "unauthenticated"


def test_revoke_unknown_key_returns_structured_404(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    response = client.delete(
        "/v1/admin/api-keys/does-not-exist",
        headers=admin_auth_headers,
    )
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["error"]["code"] == "api_key_not_found"
    assert body["error"]["details"]["key_id"] == "does-not-exist"


def test_issue_requires_admin_scope(
    client: TestClient,
    query_auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        json={"label": "no-admin"},
        headers=query_auth_headers,
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "permission_denied"

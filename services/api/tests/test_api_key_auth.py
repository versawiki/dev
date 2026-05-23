"""Auth middleware behaviour (M1-BE-02).

Covers all the negative paths the ticket calls out — every one of
these maps to a way an attacker could try to bypass auth — plus the
happy path.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from versawiki_api.auth.keys import (
    InMemoryApiKeyStore,
    RedisCachedApiKeyStore,
    assemble_token,
    parse_token,
)
from versawiki_api.auth.middleware import api_key_required


TENANT = "stub-tenant-id"


# ---------------------------------------------------------------------------
# End-to-end through the FastAPI app
# ---------------------------------------------------------------------------

def test_missing_authorization_header_returns_401(client: TestClient) -> None:
    response = client.get(f"/v1/admin/tenants/{TENANT}/api-keys")
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthenticated"


def test_malformed_authorization_header_returns_401(client: TestClient) -> None:
    # Wrong scheme
    response = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers={"Authorization": "Basic vw_aaaaaaaaaaaa_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    )
    assert response.status_code == 401
    # No space at all
    response = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers={"Authorization": "vw_aaaaaaaaaaaa_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
    )
    assert response.status_code == 401


def test_malformed_token_shape_returns_401(client: TestClient) -> None:
    # Not vw_-prefixed
    response = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers={"Authorization": "Bearer not-our-format"},
    )
    assert response.status_code == 401
    # Right namespace, wrong number of parts
    response = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers={"Authorization": "Bearer vw_onlyoneparthere"},
    )
    assert response.status_code == 401


def test_unknown_prefix_returns_401(client: TestClient) -> None:
    response = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers={"Authorization": "Bearer vw_unknownprefx_secretsecretsecretsecretsecre"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_revoked_token_returns_401(
    client: TestClient,
    admin_auth_headers: dict[str, str],
) -> None:
    issued = client.post(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        json={"label": "to-revoke", "scopes": ["query"]},
        headers=admin_auth_headers,
    ).json()
    raw_token = issued["token"]
    key_id = issued["api_key"]["id"]

    # Revoke it.
    client.delete(
        f"/v1/admin/api-keys/{key_id}",
        headers=admin_auth_headers,
    )

    # Now hit an admin endpoint with the revoked token. (Listing also
    # requires admin scope, but our revoked key isn't admin anyway —
    # the 401 from auth fires before the scope check.)
    response = client.get(
        f"/v1/admin/tenants/{TENANT}/api-keys",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_valid_token_resolves_to_api_key_via_dep() -> None:
    """Direct unit test of the dep — confirms it returns an ApiKey object."""
    store = RedisCachedApiKeyStore(InMemoryApiKeyStore())

    async def run() -> None:
        key, raw_token = await store.issue(
            tenant_id="acme", label="t", scopes=("query",),
        )

        resolved = await api_key_required(
            store=store,
            authorization=f"Bearer {raw_token}",
        )
        assert resolved.id == key.id
        assert resolved.tenant_id == "acme"
        assert resolved.prefix == key.prefix
        assert resolved.has_scope("query") is True
        assert resolved.has_scope("admin") is False
        # last_used_at is bumped on lookup
        assert resolved.last_used_at is not None

    asyncio.new_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
# Token-format unit tests
# ---------------------------------------------------------------------------

def test_assemble_and_parse_token_roundtrip() -> None:
    raw = assemble_token("abcdefghijkl", "x" * 32)
    assert raw == "vw_abcdefghijkl_" + "x" * 32
    parsed = parse_token(raw)
    assert parsed == ("abcdefghijkl", "x" * 32)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "vw_",
        "vw_only_one",
        "foo_prefix_secret",
        "vw__secret",
        "vw_prefix_",
        "not even close",
    ],
)
def test_parse_token_rejects_malformed(bad: str) -> None:
    assert parse_token(bad) is None

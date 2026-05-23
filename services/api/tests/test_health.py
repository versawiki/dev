"""/healthz contract test.

The exact JSON shape is asserted because the load balancer and the
client smoke tests depend on it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from httpx import AsyncClient


def test_healthz_returns_expected_payload(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "versawiki-api",
        "version": "0.1.0",
    }


async def test_healthz_returns_expected_payload_async(async_client: AsyncClient) -> None:
    response = await async_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "versawiki-api",
        "version": "0.1.0",
    }


def test_readyz_returns_check_list(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "versawiki-api"
    assert body["version"] == "0.1.0"
    assert body["env"] == "test"
    names = {check["name"] for check in body["checks"]}
    # The shape must already advertise db + redis so BE-02/BE-03 don't
    # have to think about adding rows; they just flip statuses.
    assert {"db", "redis"}.issubset(names)

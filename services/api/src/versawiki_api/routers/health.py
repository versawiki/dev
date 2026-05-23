"""Liveness + readiness probes.

- ``/healthz``: process is up. Returns 200 unconditionally. Used by
  the load balancer and by clients (web/desktop/mobile) to confirm
  the service is reachable before sending real traffic.
- ``/readyz``: dependencies are reachable. Today it's a stub that
  reports the same payload; BE-03 wires the DB ping and BE-02 wires
  the Redis ping. Returns 503 once any dependency fails.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from .. import __service_name__, __version__
from ..config import Settings
from ..deps import settings_dep
from ..schemas.common import HealthResponse, ReadinessCheck, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness probe.",
    description="Returns 200 if the process is running.",
)
def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=__service_name__,
        version=__version__,
    )


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    summary="Readiness probe.",
    description=(
        "Returns 200 if all critical dependencies are reachable. "
        "DB and Redis checks are added by BE-03 and BE-02 respectively."
    ),
)
def readyz(settings: Annotated[Settings, Depends(settings_dep)]) -> ReadinessResponse:
    # No dependency wiring yet -> always 'ok'. When BE-03/BE-02 land they
    # will append ReadinessCheck entries and return 503 if any fail.
    checks: list[ReadinessCheck] = []
    # Placeholder rows so the response shape is informative:
    checks.append(ReadinessCheck(name="db", status="not_configured", detail="BE-03 will wire."))
    checks.append(ReadinessCheck(name="redis", status="not_configured", detail="BE-02 will wire."))

    return ReadinessResponse(
        status="ok",
        service=__service_name__,
        version=__version__,
        env=settings.env,
        checks=checks,
    )

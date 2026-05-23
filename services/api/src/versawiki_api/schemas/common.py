"""Cross-cutting Pydantic models: error envelope + pagination."""

from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Error envelope (paired with errors.install_error_handlers)
# ---------------------------------------------------------------------------

class ErrorPayload(BaseModel):
    """Inner payload of an error response."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        ...,
        description="Machine-readable error code (snake_case, stable across versions).",
        examples=["tenant_not_found", "validation_error", "unauthenticated"],
    )
    message: str = Field(..., description="Human-readable description.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured details. Shape varies by code.",
    )


class ErrorEnvelope(BaseModel):
    """Outer envelope. All error responses have this shape."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorPayload


# ---------------------------------------------------------------------------
# Health + readiness
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field("ok", description="Always 'ok' if the process is up.")
    service: str
    version: str


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str = Field(
        ...,
        description="'ok', 'fail', or 'not_configured' for not-yet-wired dependencies.",
    )
    detail: str | None = None


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    version: str
    env: str
    checks: list[ReadinessCheck] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginationParams(BaseModel):
    """Query-string pagination params.

    Used as a FastAPI dependency via ``PaginationParamsDep``. Limit is
    capped so an MCP client can't accidentally request a 100k-row page.
    """

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginationParams:
    return PaginationParams(limit=limit, offset=offset)


PaginationParamsDep = Annotated[PaginationParams, Depends(pagination_params)]


class PaginatedList(BaseModel, Generic[T]):
    """Generic paginated list response."""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int = Field(..., description="Total items across all pages.")
    limit: int
    offset: int

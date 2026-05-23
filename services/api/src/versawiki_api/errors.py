"""Typed exceptions + FastAPI handlers.

All API errors flow through ``ErrorEnvelope`` so clients (web, desktop,
mobile, MCP) get a single, stable shape::

    {"error": {"code": "tenant_not_found", "message": "...", "details": {...}}}

Subclass ``VersawikiHTTPException`` rather than raising raw
``HTTPException``; the ``code`` field is what client code branches on,
and we want a finite, documented vocabulary.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .schemas.common import ErrorEnvelope, ErrorPayload


class VersawikiHTTPException(StarletteHTTPException):
    """Base for all typed HTTP exceptions in this service."""

    default_status_code: int = 500
    default_code: str = "internal_error"
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        *,
        status_code: int | None = None,
        code: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code or self.default_code
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(
            status_code=status_code or self.default_status_code,
            detail=self.message,
            headers=headers,
        )


class TenantNotFound(VersawikiHTTPException):
    default_status_code = 404
    default_code = "tenant_not_found"
    default_message = "Tenant not found."


class TenantAlreadyExists(VersawikiHTTPException):
    default_status_code = 409
    default_code = "tenant_already_exists"
    default_message = "A tenant with that slug already exists."


class Unauthenticated(VersawikiHTTPException):
    default_status_code = 401
    default_code = "unauthenticated"
    default_message = "Missing or invalid API key."


# Alias for BE-02's ticket spec, which uses 'UnauthorizedError' / 'ForbiddenError'
# vocabulary. Keep both names live so route code can read either way.
UnauthorizedError = Unauthenticated


class PermissionDenied(VersawikiHTTPException):
    default_status_code = 403
    default_code = "permission_denied"
    default_message = "API key lacks the required scope."


ForbiddenError = PermissionDenied


class ApiKeyNotFound(VersawikiHTTPException):
    default_status_code = 404
    default_code = "api_key_not_found"
    default_message = "API key not found."


class TenantScopeMismatch(VersawikiHTTPException):
    """The API key's tenant does not match the path tenant_id.

    Cross-tenant access is forbidden: a key issued for tenant A cannot
    query tenant B even when the path parameter says so. We return 403
    (the request was authenticated; the *scope* is wrong) with a stable
    machine-readable code so clients can branch on it.
    """

    default_status_code = 403
    default_code = "tenant_scope_mismatch"
    default_message = (
        "The API key is not authorized for this tenant. "
        "Cross-tenant access is forbidden."
    )


class NotImplementedYet(VersawikiHTTPException):
    """Used by stub routes that future tickets will fill in."""

    default_status_code = 501
    default_code = "not_implemented"
    default_message = "This endpoint is not implemented yet."


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = ErrorEnvelope(error=ErrorPayload(code=code, message=message, details=details or {}))
    return payload.model_dump(mode="json")


def _is_jsonable(value: object) -> bool:
    return isinstance(value, (str, int, float, bool, type(None), list, tuple, dict))


def _scrub_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip non-JSON-serializable bits (e.g. ValueError in ``ctx``).

    Pydantic v2 stuffs the originating exception into ``ctx['error']``
    which JSONResponse can't encode. We replace any non-serializable
    leaf with its ``str()`` so the wire payload stays valid.
    """
    scrubbed: list[dict[str, Any]] = []
    for err in errors:
        cleaned: dict[str, Any] = {}
        for k, v in err.items():
            if k == "ctx" and isinstance(v, dict):
                cleaned[k] = {ck: (cv if _is_jsonable(cv) else str(cv)) for ck, cv in v.items()}
            elif _is_jsonable(v):
                cleaned[k] = v
            else:
                cleaned[k] = str(v)
        scrubbed.append(cleaned)
    return scrubbed


async def _versawiki_exception_handler(
    request: Request,  # noqa: ARG001 - FastAPI handler signature
    exc: VersawikiHTTPException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, exc.details),
        headers=exc.headers,
    )


async def _starlette_exception_handler(
    request: Request,  # noqa: ARG001
    exc: StarletteHTTPException,
) -> JSONResponse:
    # Any HTTPException raised by FastAPI internals (404 from missing route, etc.).
    code = "http_error"
    if exc.status_code == 404:
        code = "not_found"
    elif exc.status_code == 405:
        code = "method_not_allowed"
    elif exc.status_code == 401:
        code = "unauthenticated"
    elif exc.status_code == 403:
        code = "permission_denied"
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message),
        headers=exc.headers,
    )


async def _validation_exception_handler(
    request: Request,  # noqa: ARG001
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_envelope(
            "validation_error",
            "Request body failed validation.",
            {"errors": _scrub_errors(exc.errors())},
        ),
    )


async def _unhandled_exception_handler(
    request: Request,  # noqa: ARG001
    exc: Exception,  # noqa: ARG001
) -> JSONResponse:
    # Last-resort. Don't leak internals to the client.
    return JSONResponse(
        status_code=500,
        content=_envelope("internal_error", "An unexpected error occurred."),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Wire all exception handlers onto a FastAPI app."""
    app.add_exception_handler(VersawikiHTTPException, _versawiki_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _starlette_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

"""FastAPI router for the per-tenant MCP endpoint.

Mounts ``POST /mcp`` (under whatever prefix the app applies — see
``versawiki_api.routers.__init__.register_routers``). The actual JSON-
RPC parsing and method dispatch lives in :mod:`.transport`; this file
is just the HTTP-layer glue:

- ``api_key_required`` resolves the bearer token to an :class:`ApiKey`
  (401 otherwise) and exposes the tenant id used by every tool call.
- ``EmbeddingProviderDep`` injects the wired embedding provider so
  ``search`` can call it.

There is no path-level ``tenant_id``. The MCP endpoint is a single URL
per deployment; the tenant is resolved purely from the API key. This
matches the v1 architecture doc § 5: "a single endpoint
``https://mcp.versawiki.io/mcp`` where the API key resolves the tenant".
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..auth.middleware import CurrentApiKey
from ..deps import EmbeddingProviderDep
from .transport import handle_mcp_post

router = APIRouter()


@router.post(
    "",
    summary="MCP-over-HTTP entry point.",
    description=(
        "Streamable MCP transport. Accepts a JSON-RPC 2.0 request body "
        "with ``initialize``, ``tools/list``, or ``tools/call``. The "
        "tenant is resolved from the ``Authorization: Bearer vw_...`` "
        "header; the request body must not carry a ``tenant_id``. "
        "With ``Accept: text/event-stream`` the response is a SSE "
        "stream carrying a single ``message`` event; otherwise a "
        "regular JSON body."
    ),
    response_model=None,
    responses={
        200: {"description": "JSON-RPC response (success or in-envelope error)."},
        401: {"description": "Missing or invalid API key."},
    },
)
async def mcp_post(
    request: Request,
    api_key: CurrentApiKey,
    embedder: EmbeddingProviderDep,
) -> Response:
    return await handle_mcp_post(
        request,
        api_key=api_key,
        embedder=embedder,
    )


__all__ = ["router"]

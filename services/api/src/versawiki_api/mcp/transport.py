"""MCP-over-HTTP streamable transport.

A minimal implementation of the Model Context Protocol's JSON-RPC 2.0
shape over HTTP. Two response modes, picked from the ``Accept`` header:

- ``Accept: text/event-stream`` -> SSE stream with one ``event: message``
  carrying the JSON-RPC response. (The streamable transport is designed
  to support multiple events per call; for the four read-only tools
  we serve here a single ``message`` event is enough.)
- Anything else -> a regular JSON response body.

Methods dispatched here:

- ``initialize`` — handshake. Returns the server's protocol version and
  capabilities. Required before tool calls in the strict spec; we don't
  enforce ordering across requests because each HTTP POST is independent.
- ``tools/list`` — advertise the four tools (see :mod:`.schemas`).
- ``tools/call`` — invoke a tool by name with an ``arguments`` dict.

Tenant identity is *always* taken from the validated API key. If a
client tries to put ``tenant_id`` in the JSON-RPC body, we reject with
``invalid_request``. That's the cross-tenant guard the meta-MCP and
LLM-agent threat models both depend on.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth.keys import ApiKey
from ..deps import EmbeddingProvider, PageStore
from ..logging import get_logger
from .schemas import TOOL_NAMES, tool_definitions
from .tools import TOOL_HANDLERS, ToolError

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

#: MCP protocol version this server advertises. The actual MCP spec is
#: a moving target; we pin a date-based version string so clients can
#: feature-detect.
MCP_PROTOCOL_VERSION: str = "2025-06-18"

#: Server identity returned in the ``initialize`` response.
SERVER_INFO: dict[str, str] = {
    "name": "versawiki-mcp",
    "version": "0.1.0",
}

#: Server capabilities. We support ``tools`` (the only category v1 ships).
SERVER_CAPABILITIES: dict[str, Any] = {
    "tools": {
        # ``listChanged: false`` — our tool list is stable across the
        # session; we don't push notifications when it changes (because
        # for now it doesn't change).
        "listChanged": False,
    },
}


# JSON-RPC 2.0 reserved error codes (spec).
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------

def _result_envelope(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_envelope(
    request_id: Any,
    code: int,
    message: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


# ---------------------------------------------------------------------------
# Method dispatch
# ---------------------------------------------------------------------------

async def _handle_initialize(
    request_id: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    # The spec lets the client propose its own protocolVersion; we
    # accept whatever they offer and echo our own. (Negotiation logic
    # gets richer as the spec evolves; today we just advertise.)
    _ = params  # currently unused; kept for future negotiation
    return _result_envelope(
        request_id,
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": SERVER_CAPABILITIES,
            "serverInfo": SERVER_INFO,
        },
    )


async def _handle_tools_list(
    request_id: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    _ = params
    return _result_envelope(request_id, {"tools": tool_definitions()})


async def _handle_tools_call(
    request_id: Any,
    params: dict[str, Any],
    *,
    tenant_id: str,
    embedder: EmbeddingProvider,
    page_store: PageStore | None = None,
) -> dict[str, Any]:
    """Dispatch a ``tools/call`` to the tool implementation.

    Cross-tenant guard: if ``arguments`` carries a ``tenant_id``, we
    refuse. The tenant is fixed by the API key; an LLM client must not
    be able to override it via the JSON-RPC body.
    """
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str):
        return _error_envelope(
            request_id,
            JSONRPC_INVALID_PARAMS,
            "tools/call requires a string 'name'.",
        )
    if not isinstance(arguments, dict):
        return _error_envelope(
            request_id,
            JSONRPC_INVALID_PARAMS,
            "tools/call 'arguments' must be an object.",
        )

    if "tenant_id" in arguments:
        # 400-equivalent in HTTP land; in JSON-RPC we use invalid_params.
        # Clients that try this are either confused or malicious; either
        # way we refuse without ever consulting the embedded value.
        log.warning(
            "mcp_cross_tenant_attempt",
            api_key_tenant_id=tenant_id,
            attempted_tenant_id=arguments.get("tenant_id"),
            tool=name,
        )
        return _error_envelope(
            request_id,
            JSONRPC_INVALID_PARAMS,
            (
                "tenant_id is not accepted in tool arguments. The tenant "
                "is fixed by the API key."
            ),
            data={"offending_field": "tenant_id"},
        )

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return _error_envelope(
            request_id,
            JSONRPC_METHOD_NOT_FOUND,
            f"Unknown tool: {name!r}.",
            data={"available_tools": list(TOOL_NAMES)},
        )

    try:
        if name == "search":
            result = await handler(
                tenant_id,
                arguments=arguments,
                embedder=embedder,
            )
        elif name == "read_page":
            result = await handler(
                tenant_id,
                arguments=arguments,
                page_store=page_store,
            )
        else:
            result = await handler(tenant_id, arguments=arguments)
    except ToolError as exc:
        return _error_envelope(
            request_id,
            exc.code,
            exc.message,
            data=exc.data,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        log.exception(
            "mcp_tool_unhandled_error",
            tenant_id=tenant_id,
            tool=name,
        )
        return _error_envelope(
            request_id,
            JSONRPC_INTERNAL_ERROR,
            "Tool raised an unhandled exception.",
            data={"tool": name, "exception": str(exc)},
        )

    return _result_envelope(request_id, result)


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

async def _dispatch(
    body: dict[str, Any],
    *,
    tenant_id: str,
    embedder: EmbeddingProvider,
    page_store: PageStore | None = None,
) -> dict[str, Any]:
    """Route a JSON-RPC request envelope to a method handler.

    Returns the response envelope (success or error) as a plain dict.
    The HTTP layer wraps it in either a JSON body or an SSE event.
    """
    if not isinstance(body, dict):
        return _error_envelope(
            None,
            JSONRPC_INVALID_REQUEST,
            "Request body must be a JSON object.",
        )
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        return _error_envelope(
            request_id,
            JSONRPC_INVALID_REQUEST,
            "Missing or non-'2.0' jsonrpc field.",
        )
    method = body.get("method")
    params = body.get("params") or {}
    if not isinstance(method, str):
        return _error_envelope(
            request_id,
            JSONRPC_INVALID_REQUEST,
            "Missing 'method' field.",
        )
    if not isinstance(params, dict):
        return _error_envelope(
            request_id,
            JSONRPC_INVALID_PARAMS,
            "'params' must be an object.",
        )

    if method == "initialize":
        return await _handle_initialize(request_id, params)
    if method == "tools/list":
        return await _handle_tools_list(request_id, params)
    if method == "tools/call":
        return await _handle_tools_call(
            request_id,
            params,
            tenant_id=tenant_id,
            embedder=embedder,
            page_store=page_store,
        )

    # ``notifications/initialized`` and similar one-way notifications:
    # for now we accept them silently. JSON-RPC says notifications have
    # no id; we still return an envelope so HTTP has something to send.
    if method.startswith("notifications/"):
        return _result_envelope(request_id, {})

    return _error_envelope(
        request_id,
        JSONRPC_METHOD_NOT_FOUND,
        f"Unknown method: {method!r}.",
    )


# ---------------------------------------------------------------------------
# HTTP entry point
# ---------------------------------------------------------------------------

def _wants_sse(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    # Strict-ish substring check: ``text/event-stream`` always appears
    # verbatim when a client wants SSE. We don't bother parsing q-values
    # — clients either ask for SSE or they don't.
    return "text/event-stream" in accept.lower()


async def _sse_iter(envelope: dict[str, Any]) -> AsyncIterator[bytes]:
    """Yield SSE-formatted bytes for a single response envelope.

    SSE event lines: ``event: <type>\n``, ``data: <json>\n``, blank line
    to terminate the event. We emit a single ``message`` event carrying
    the full envelope, then close. The streamable MCP transport allows
    multi-event streams; we ship one event for now because none of the
    v1 tools produce partial results.
    """
    payload = json.dumps(envelope, separators=(",", ":"))
    yield f"event: message\ndata: {payload}\n\n".encode("utf-8")


async def handle_mcp_post(
    request: Request,
    *,
    api_key: ApiKey,
    embedder: EmbeddingProvider,
    page_store: PageStore | None = None,
) -> JSONResponse | StreamingResponse:
    """Top-level POST handler. Returns either JSON or an SSE stream."""
    try:
        raw = await request.body()
    except Exception:  # noqa: BLE001
        envelope = _error_envelope(
            None,
            JSONRPC_PARSE_ERROR,
            "Failed to read request body.",
        )
        return JSONResponse(envelope, status_code=200)

    if not raw:
        envelope = _error_envelope(
            None,
            JSONRPC_INVALID_REQUEST,
            "Empty request body.",
        )
        return JSONResponse(envelope, status_code=200)

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        envelope = _error_envelope(
            None,
            JSONRPC_PARSE_ERROR,
            f"Invalid JSON: {exc.msg}",
        )
        return JSONResponse(envelope, status_code=200)

    envelope = await _dispatch(
        body,
        tenant_id=api_key.tenant_id,
        embedder=embedder,
        page_store=page_store,
    )

    if _wants_sse(request):
        return StreamingResponse(
            _sse_iter(envelope),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return JSONResponse(envelope, status_code=200)


__all__ = [
    "MCP_PROTOCOL_VERSION",
    "SERVER_CAPABILITIES",
    "SERVER_INFO",
    "handle_mcp_post",
]

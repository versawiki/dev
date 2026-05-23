"""``GET /v1/tenants/{tenant_id}/pages/...`` — fetch wiki pages.

Wiki pages are derived artifacts built by ING-05 (page builder). They
are persisted via :class:`PageStore` (in-memory for tests, Postgres
for production); the router reads them out and returns the canonical
envelope.

Three routes live here:

  - ``GET /tenants/{tid}/pages/{page_id}`` — by id.
  - ``GET /tenants/{tid}/pages?slug=...`` — by slug.
  - ``GET /tenants/{tid}/pages?ontology_node=...`` — list pages for a
    node.

All three are tenant-scoped via :func:`resolve_tenant`: a wrong-tenant
key gets the 403 ``tenant_scope_mismatch`` before any store lookup runs.

Stale-on-event materialisation (per `DECISIONS.md`): if a returned
page is stale we serve it immediately with a ``Cache-Control: stale=true``
header and fire a background rebuild via the configured rebuilder hook
(no-op until the ingestion service wires one in). Readers never block.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Awaitable, Callable, Optional

from fastapi import APIRouter, BackgroundTasks, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ...deps import PageStoreDep
from ...errors import VersawikiHTTPException
from ...logging import get_logger
from ...pages_store import WikiPageRecord
from ...services_api_tenant import TenantSessionDep

log = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response envelopes
# ---------------------------------------------------------------------------


class WikiPage(BaseModel):
    """Wire shape of a wiki page.

    Pinned for client codegen. Fields mirror :class:`WikiPageRecord`
    but the wire type is what clients depend on; if the persistence
    record grows a new field, this envelope can stay stable until we
    explicitly version it.
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    slug: str
    title: str
    summary: str
    body_md: str
    body_html: str = ""
    primary_ontology_node_id: str | None = Field(default=None)
    chunk_ids: list[str] = Field(default_factory=list)
    related_page_ids: list[str] = Field(default_factory=list)
    last_built_at: str | None = Field(default=None)
    is_stale: bool = False
    version: int = 1
    source_uri_count: int = 0
    predominant_doc_types: list[str] = Field(default_factory=list)


class WikiPageListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WikiPage]
    total: int


class PageNotFound(VersawikiHTTPException):
    default_status_code = 404
    default_code = "page_not_found"
    default_message = "Wiki page not found."


def _to_wire(record: WikiPageRecord) -> WikiPage:
    """Map a stored :class:`WikiPageRecord` onto the wire shape."""
    last_built = (
        record.updated_at.isoformat() if isinstance(record.updated_at, datetime) else None
    )
    return WikiPage(
        page_id=record.id,
        slug=record.slug,
        title=record.title,
        summary=record.summary,
        body_md=record.body_markdown,
        body_html="",
        primary_ontology_node_id=record.ontology_node_id,
        chunk_ids=list(record.chunk_ids),
        related_page_ids=list(record.related_page_ids),
        last_built_at=last_built,
        is_stale=record.is_stale,
        version=record.version,
        source_uri_count=record.source_uri_count,
        predominant_doc_types=list(record.predominant_doc_types),
    )


# ---------------------------------------------------------------------------
# Background-rebuild hook
# ---------------------------------------------------------------------------

#: A coroutine the API fires when it serves a stale page. The ingestion
#: side will wire one in (it must accept tenant_id + page_id). Tests
#: install their own to assert the hook fires.
RebuildHook = Callable[[str, str], Awaitable[None]]

_REBUILD_HOOK: Optional[RebuildHook] = None


def set_rebuild_hook(hook: Optional[RebuildHook]) -> None:
    """Install (or clear) the global rebuild hook.

    Tests use this to verify that serving a stale page kicks off a
    background rebuild. Production wires the ingestion service's
    rebuild path.
    """
    global _REBUILD_HOOK
    _REBUILD_HOOK = hook


async def _kick_rebuild(tenant_id: str, page_id: str) -> None:
    hook = _REBUILD_HOOK
    if hook is None:
        return
    try:
        await hook(tenant_id, page_id)
    except Exception:  # noqa: BLE001 - never let a hook bubble out
        log.exception(
            "page_rebuild_hook_failed",
            tenant_id=tenant_id,
            page_id=page_id,
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/tenants/{tenant_id}/pages/{page_id}",
    response_model=WikiPage,
    summary="Fetch a wiki page by id.",
    description=(
        "Returns the wiki page produced by the page-builder (ING-05). "
        "If the page is stale (the ingestion-event bus has flagged it "
        "for rebuild), the current version is served immediately with "
        "a ``Cache-Control: stale=true`` header and a background "
        "rebuild is enqueued. The cross-tenant guard runs first so a "
        "foreign key can never probe page existence."
    ),
    responses={
        401: {"description": "Missing or invalid API key."},
        403: {"description": "API key is not authorized for this tenant."},
        404: {"description": "Page not found, OR tenant not found."},
    },
)
async def get_page(
    page_id: str,
    tenant: TenantSessionDep,
    page_store: PageStoreDep,
    response: Response,
    background_tasks: BackgroundTasks,
) -> WikiPage:
    record = await page_store.get(tenant.tenant_id, page_id)
    if record is None:
        log.info(
            "page_lookup_missing",
            tenant_id=tenant.tenant_id,
            page_id=page_id,
        )
        raise PageNotFound(
            details={"tenant_id": tenant.tenant_id, "page_id": page_id},
        )
    if record.is_stale:
        response.headers["Cache-Control"] = "stale=true"
        background_tasks.add_task(
            _kick_rebuild, tenant.tenant_id, page_id
        )
        log.info(
            "page_served_stale",
            tenant_id=tenant.tenant_id,
            page_id=page_id,
        )
    return _to_wire(record)


@router.get(
    "/tenants/{tenant_id}/pages",
    response_model=WikiPageListResponse,
    summary="List or look up pages (by slug or ontology_node).",
    description=(
        "Either ``slug`` or ``ontology_node`` must be supplied. With "
        "``slug``, returns a single-item list (or empty). With "
        "``ontology_node``, returns every page attached to that node."
    ),
    responses={
        400: {"description": "Neither slug nor ontology_node was supplied."},
        401: {"description": "Missing or invalid API key."},
        403: {"description": "API key is not authorized for this tenant."},
    },
)
async def list_pages(
    tenant: TenantSessionDep,
    page_store: PageStoreDep,
    slug: Annotated[str | None, Query()] = None,
    ontology_node: Annotated[str | None, Query()] = None,
) -> WikiPageListResponse:
    if slug is None and ontology_node is None:
        # 400 via VersawikiHTTPException so it lands in the standard envelope.
        raise VersawikiHTTPException(
            status_code=400,
            code="missing_filter",
            message="Either 'slug' or 'ontology_node' must be supplied.",
        )

    items: list[WikiPageRecord] = []
    if slug is not None:
        record = await page_store.get_by_slug(tenant.tenant_id, slug)
        if record is not None:
            items.append(record)
    else:
        assert ontology_node is not None  # narrowed
        items = await page_store.list_for_node(tenant.tenant_id, ontology_node)

    return WikiPageListResponse(
        items=[_to_wire(r) for r in items],
        total=len(items),
    )


__all__ = [
    "PageNotFound",
    "WikiPage",
    "WikiPageListResponse",
    "router",
    "set_rebuild_hook",
]

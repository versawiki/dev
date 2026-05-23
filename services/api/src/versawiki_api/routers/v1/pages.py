"""``GET /v1/tenants/{tenant_id}/pages/{page_id}`` — fetch a wiki page.

Wiki pages are derived artifacts built by ING-05 (page builder). Until
that ticket lands, every page lookup is a structured 404. The shape of
the response is pinned here so client codegen is stable.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ...errors import VersawikiHTTPException
from ...logging import get_logger
from ...services_api_tenant import TenantSessionDep

log = get_logger(__name__)

router = APIRouter()


class WikiPage(BaseModel):
    """A rendered wiki page.

    ``body_html`` is the pre-rendered HTML the UI displays; ``body_md``
    is the source markdown. Both are produced by ING-05.
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    slug: str
    title: str
    body_md: str
    body_html: str
    primary_ontology_node_id: str | None = Field(default=None)
    last_built_at: str | None = Field(default=None)


class PageNotFound(VersawikiHTTPException):
    default_status_code = 404
    default_code = "page_not_found"
    default_message = "Wiki page not found."


@router.get(
    "/tenants/{tenant_id}/pages/{page_id}",
    response_model=WikiPage,
    summary="Fetch a wiki page by id.",
    description=(
        "Renders the wiki page produced by the page-builder (ING-05). "
        "Until that ticket lands, every call returns a structured 404 "
        "(``page_not_found``). The cross-tenant guard still runs first, "
        "so a foreign key cannot probe page existence."
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
) -> WikiPage:
    # BE-04 stub: ING-05 has not yet persisted any pages.
    log.info(
        "page_lookup_missing_stub",
        tenant_id=tenant.tenant_id,
        page_id=page_id,
    )
    raise PageNotFound(
        details={"tenant_id": tenant.tenant_id, "page_id": page_id},
    )


__all__ = ["router", "WikiPage", "PageNotFound"]

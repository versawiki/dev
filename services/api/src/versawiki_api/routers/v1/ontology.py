"""``GET /v1/tenants/{tenant_id}/ontology`` — browse the ontology tree.

The ontology is induced by ING-04 (ontology builder) and refined by
the meta-MCP's learned skills. Today the per-tenant ``ontology_nodes``
table is a stub column shell, so the BE-04 stub returns an
empty-tree-shaped response. Tests assert shape only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from ...logging import get_logger
from ...services_api_tenant import TenantSessionDep

log = get_logger(__name__)

router = APIRouter()


class OntologyNode(BaseModel):
    """A node in the tenant's ontology tree.

    ``children`` is recursive — clients walk it depth-first to render a
    sidebar tree. ``kind`` is one of ``category`` / ``entity`` /
    ``topic`` per the v1 data model.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str = ""
    kind: str = "category"
    children: list["OntologyNode"] = Field(default_factory=list)


OntologyNode.model_rebuild()


class OntologyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: OntologyNode


@router.get(
    "/tenants/{tenant_id}/ontology",
    response_model=OntologyResponse,
    summary="Return the tenant's ontology tree (or a subtree).",
    description=(
        "Returns the full tenant ontology rooted at ``root``. Pass "
        "``node_id`` to return only that subtree. Today's BE-04 stub "
        "returns an empty tree until ING-04 wires real ``ontology_nodes`` "
        "persistence."
    ),
    responses={
        401: {"description": "Missing or invalid API key."},
        403: {"description": "API key is not authorized for this tenant."},
        404: {"description": "Tenant not found."},
    },
)
async def get_ontology(
    tenant: TenantSessionDep,
    node_id: Annotated[str | None, Query()] = None,
) -> OntologyResponse:
    log.info(
        "ontology_lookup_stub",
        tenant_id=tenant.tenant_id,
        node_id=node_id,
    )
    root_id = node_id or "root"
    return OntologyResponse(
        root=OntologyNode(id=root_id, label="", kind="category", children=[]),
    )


__all__ = ["router", "OntologyNode", "OntologyResponse"]

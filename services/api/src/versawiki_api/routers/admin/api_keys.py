"""Admin endpoints for tenant API keys.

Routes:

- ``POST /v1/admin/tenants/{tenant_id}/api-keys`` — issue a key. The
  response is the **only** place the raw token appears on the wire.
- ``GET /v1/admin/tenants/{tenant_id}/api-keys`` — list. Returns
  prefixes + metadata; never the raw token, never the hash.
- ``DELETE /v1/admin/api-keys/{key_id}`` — revoke. Subsequent
  ``api_key_required`` lookups for that token return 401.

All routes require the ``admin`` scope. BE-03 swaps the in-memory
store for the Postgres-backed one; this router does not change.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from ...auth.keys import ApiKey
from ...auth.middleware import ApiKeyStoreDep
from ...deps import AdminApiKey
from ...errors import ApiKeyNotFound
from ...schemas.api_key import ApiKeyOut, IssueApiKeyRequest, IssuedApiKey
from ...schemas.common import PaginatedList

router = APIRouter()


def _to_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        tenant_id=key.tenant_id,
        prefix=key.prefix,
        label=key.label,
        scopes=key.scopes,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


@router.post(
    "/tenants/{tenant_id}/api-keys",
    response_model=IssuedApiKey,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new API key for a tenant.",
    description=(
        "Returns the raw ``vw_<prefix>_<secret>`` token exactly once. "
        "The caller must store it now; subsequent list endpoints expose "
        "only the prefix and metadata."
    ),
)
async def issue_api_key(
    tenant_id: str,
    payload: IssueApiKeyRequest,
    store: ApiKeyStoreDep,
    _admin: AdminApiKey,
) -> IssuedApiKey:
    key, raw_token = await store.issue(
        tenant_id=tenant_id,
        label=payload.label,
        scopes=tuple(payload.scopes),
    )
    return IssuedApiKey(api_key=_to_out(key), token=raw_token)


@router.get(
    "/tenants/{tenant_id}/api-keys",
    response_model=PaginatedList[ApiKeyOut],
    summary="List API keys for a tenant.",
    description=(
        "Returns prefixes + metadata. Never includes the raw token or "
        "the hash. Includes revoked keys (with ``revoked_at`` populated) "
        "so the audit trail is visible."
    ),
)
async def list_api_keys(
    tenant_id: str,
    store: ApiKeyStoreDep,
    _admin: AdminApiKey,
) -> PaginatedList[ApiKeyOut]:
    keys = await store.list_for_tenant(tenant_id)
    items = [_to_out(k) for k in keys]
    return PaginatedList[ApiKeyOut](
        items=items,
        total=len(items),
        limit=len(items) if items else 50,
        offset=0,
    )


@router.delete(
    "/api-keys/{key_id}",
    response_model=ApiKeyOut,
    summary="Revoke an API key.",
    description=(
        "Marks the key revoked. Subsequent ``Authorization: Bearer "
        "vw_<prefix>_<secret>`` requests for this key return 401."
    ),
    responses={404: {"description": "API key not found."}},
)
async def revoke_api_key(
    key_id: str,
    store: ApiKeyStoreDep,
    _admin: AdminApiKey,
) -> ApiKeyOut:
    revoked = await store.revoke(key_id)
    if revoked is None:
        raise ApiKeyNotFound(details={"key_id": key_id})
    return _to_out(revoked)

"""API-key wire schemas.

These are intentionally separate from the in-memory :class:`ApiKey`
domain model so the wire shape can evolve without touching the auth
internals.

The key invariant: the raw token appears in exactly one response
shape — :class:`IssuedApiKey` — and only when a key is first issued.
Every other endpoint (list, revoke) returns :class:`ApiKeyOut`, which
omits the raw token entirely.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Label = Annotated[
    str,
    StringConstraints(min_length=1, max_length=120, strip_whitespace=True),
]


class IssueApiKeyRequest(BaseModel):
    """POST body for ``/v1/admin/tenants/{tid}/api-keys``."""

    model_config = ConfigDict(extra="forbid")

    label: Label | None = Field(
        default=None,
        description="Human-readable label (e.g. 'web-app', 'mcp-claude').",
    )
    scopes: tuple[str, ...] = Field(
        default=("query",),
        description=(
            "Granted scopes. ``query`` is the default for MCP/read access; "
            "``admin`` unlocks tenant + key management."
        ),
    )


class ApiKeyOut(BaseModel):
    """An API key on the wire. Hash + raw token are deliberately absent."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str
    prefix: str = Field(
        ...,
        description=(
            "URL-safe prefix portion of the token. Safe to log; the secret "
            "portion is never exposed after issuance."
        ),
    )
    label: str | None = None
    scopes: tuple[str, ...] = ("query",)
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class IssuedApiKey(BaseModel):
    """Issue response. The **only** place ``token`` ever appears on the wire."""

    model_config = ConfigDict(extra="forbid")

    api_key: ApiKeyOut
    token: str = Field(
        ...,
        description=(
            "The raw ``vw_<prefix>_<secret>`` token. Returned exactly once; "
            "the caller must store it now or re-issue."
        ),
    )

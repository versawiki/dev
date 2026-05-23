"""Tenant schemas. Shared by the admin routes and (later) the MCP layer."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# Slug rules: lowercase, alphanumeric + hyphen, 3-40 chars. Used as part
# of the Postgres schema name (vw_<slug>), so anything that's safe to
# splice into an identifier (after we double-check at the DB layer)
# must pass this regex first.
_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")

Plan = Literal["free", "pro", "enterprise"]

Slug = Annotated[
    str,
    StringConstraints(min_length=3, max_length=40, strip_whitespace=True, to_lower=True),
]


class CreateTenantRequest(BaseModel):
    """POST /v1/admin/tenants body."""

    model_config = ConfigDict(extra="forbid")

    slug: Slug = Field(
        ...,
        description="URL-safe identifier. Lowercase, alphanumeric + hyphen, 3-40 chars.",
        examples=["acme", "globex-eng"],
    )
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Human-readable tenant name.",
    )
    plan: Plan = Field("free", description="Billing plan.")

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        if not _SLUG_PATTERN.match(value):
            raise ValueError(
                "Slug must start with a letter, contain only lowercase letters, "
                "digits, and hyphens, and not start or end with a hyphen.",
            )
        if "--" in value:
            raise ValueError("Slug must not contain consecutive hyphens.")
        return value


class TenantOut(BaseModel):
    """Tenant resource as returned by the API."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Server-issued opaque id (UUIDv7 once BE-03 lands).")
    slug: Slug
    display_name: str
    plan: Plan
    db_schema_name: str = Field(
        ...,
        description="Postgres schema name (vw_<slug>). Informational; not client-settable.",
    )
    created_at: datetime

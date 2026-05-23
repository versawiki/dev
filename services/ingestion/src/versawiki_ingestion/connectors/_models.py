"""Pydantic v2 models used by every connector.

These are deliberately small. The pipeline that consumes them (chunker,
embedder, classifier, persister — M1-ING-02, M1-BE-03+) is connector-agnostic;
it only sees `ResourceRef` and `ChangeEvent`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChangeKind(str, Enum):
    """What happened to a resource between two `list()` passes."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class ResourceRef(BaseModel):
    """A pointer to one document in a connector's source.

    `uri` is the connector-agnostic identity: for `LocalFolderConnector` it's
    the path string under the source root; for `GDriveConnector` (M2) it's the
    Drive file ID. The pipeline keys on `(tenant_id, source_id, uri)` and on
    `content_hash` for dedup.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(..., description="Tenant slug from vw_admin.tenants.")
    source_id: str = Field(..., description="Source row id within the tenant schema.")
    uri: str = Field(..., description="Connector-specific stable identifier.")
    # Display fields; not load-bearing for identity.
    name: str = Field(..., description="Human-readable filename.")
    mime_type: Optional[str] = Field(default=None, description="Best-guess MIME type.")
    size_bytes: Optional[int] = Field(default=None, ge=0)
    last_modified: Optional[datetime] = Field(default=None)
    # Connector hints — opaque to the pipeline; used by `watch()` change-detection.
    etag: Optional[str] = Field(default=None, description="Connector-specific change token.")

    @property
    def extension(self) -> str:
        """Lowercase file extension including the dot, e.g. `.pdf`. Empty if none."""
        return PurePosixPath(self.name).suffix.lower()


class ChangeEvent(BaseModel):
    """Emitted by `Connector.watch()` when a resource is added / modified / deleted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ChangeKind
    ref: ResourceRef
    observed_at: datetime
    # For DELETED, the ref is whatever we last knew about the resource; `etag` is None.
    # For ADDED, ref is the new resource as just discovered.
    # For MODIFIED, ref is the new state; the caller may have a prior ref cached.
    prior_etag: Optional[str] = Field(default=None)


# Re-exported so callers can `Literal["added", ...]` against the same vocabulary.
ChangeKindLiteral = Literal["added", "modified", "deleted"]

"""versawiki_api — Query API, admin surface, and (forthcoming) MCP endpoint.

This is the modular-monolith package for service 1.2 (Query API) and 1.3
(per-tenant MCP endpoint) from docs/architecture/v1.md. Workers (RQ-driven
ingestion) import the same package as a library to stay consistent on
config, logging, schemas, and DB sessions.
"""

from __future__ import annotations

__version__ = "0.1.0"
__service_name__ = "versawiki-api"

__all__ = ["__version__", "__service_name__"]

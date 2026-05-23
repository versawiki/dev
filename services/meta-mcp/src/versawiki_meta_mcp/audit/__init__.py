"""Tenant-local audit log.

v1 is JSONL on disk under the tenant directory; v2 (`M1-MCP-02`) replaces
the writer with a per-tenant Postgres-backed implementation. The public
interface in this package is what callers should import.

PRIVACY INVARIANT: the audit log NEVER stores the offending payload. It
stores only `payload_hash + reason_code + stage + timestamp`. See the
top-of-file comment in `tenant_audit_log.py` for the full statement.
"""

from .tenant_audit_log import TenantAuditLog

__all__ = ["TenantAuditLog"]

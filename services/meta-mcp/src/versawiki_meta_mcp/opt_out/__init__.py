"""Per-tenant opt-out flag API + persistence (M1-MCP-05).

Public surface:
    TenantOptOutStore   — persistent flag store (set / get / clear / list)
    load_tenant_config  — build a TenantSignatureConfig with opt_out loaded
                          from the store (the primary integration point)

The in-memory flag (`TenantSignatureConfig.opt_out`) was already honoured by
the collector and the skill applier. This module owns *how* that flag becomes
True on disk — the persistence and the API that sets it.
"""

from .store import TenantOptOutStore, load_tenant_config

__all__ = ["TenantOptOutStore", "load_tenant_config"]

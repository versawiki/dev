# versawiki meta-MCP

The self-improving meta layer for versawiki. Owns the tenant -> meta-MCP
privacy boundary.

## What's here in M1

- `versawiki_meta_mcp.schema.observation` — Pydantic v2 wire schema for the
  `DomainObservation` envelope and 8 payload variants. Source of truth lives
  in `docs/architecture/domain-observation-v1.md`.
- `versawiki_meta_mcp.checkers` — the 5-stage pre-emit static checker
  pipeline (ticket `M1-MCP-01a`). This is the operational enforcement of
  versawiki's privacy promise: no `DomainObservation` may leave a tenant
  process and no learned-skill markdown may be committed until it has
  passed every stage.
- `versawiki_meta_mcp.audit` — tenant-local audit log. v1 is a JSONL
  file under the tenant directory; v2 (`M1-MCP-02`) is per-tenant
  Postgres. Failed-check entries record `payload_hash + reason_code`
  only — never the offending payload itself.

## Pipeline stages (in order; first hard failure short-circuits)

1. **schema_validate** — Pydantic strict validation; `extra="forbid"`.
2. **forbidden_field_name_scan** — block field names from §4 of the spec
   anywhere in the nested payload tree (case-insensitive).
3. **pii_ner** — spaCy `en_core_web_sm` NER + regex layer for emails,
   phones, SSN-shape numbers, URLs. Regex-only fallback when the spaCy
   model is unavailable.
4. **numeric_pattern** — every numeric leaf must be a bucket label, a
   ratio in [0, 1], a quantile from the fixed set, or a structural
   count < 1000 explicitly allowed by the schema. Raw scalars otherwise.
5. **quote_near_quote** — trigram overlap against a tenant-supplied
   corpus shingle set. Stub corpus in v1; real integration in `M1-MCP-02`.
6. **opt_out_gate** — if `opt_out_flag == True`, reject everything for
   the meta store (tenant-local audit log still receives the envelope).

## Running tests

```
cd services/meta-mcp
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vwpyc PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -q tests/
```

# Prior-art MCP code worth reusing

Ticket: **M0-05**. Status: **draft v1**, written 2026-05-22 by the Researcher.

This file catalogues what we can learn from the four MCP servers that
already exist in Josh's universe, and what versawiki must change or add.
The full source isn't in this session — only the runbook
(`domain-expert-mcps` SKILL.md), the troubleshooting notes, and the live
MCP tools. I probed two of the tools to confirm behaviour. The "what we
still need from Josh's repo" section at the end lists what a full audit
would require.

---

## What I had access to in this session

1. The `domain-expert-mcps` skill: SKILL.md (architecture and runbook) and
   `references/troubleshooting.md` (real bugs hit during operation).
2. Four live MCP servers, all exposing the same 14 tools:
   - `mcp__project-docs-bc__*` — Bluewave Construction
   - `mcp__project-docs-ae__*` — Aspen Engineering
   - `mcp__project-docs-ams__*` — AMS Renewable Energy
   - `mcp__renewable-knowledge__*` — shared domain knowledge
3. Live probes (named below).

Locations on disk (from the skill):

- Skill: `C:\Users\joshu\AppData\Roaming\Claude\local-agent-mode-sessions\skills-plugin\5d6209f6-e84d-48b9-ada4-784ba1619d8b\e8ddb70c-d838-477c-af1b-5301bad4651e\skills\domain-expert-mcps\`
- Servers on the VM: `35.226.25.117`, ports 8080–8083, folders
  `/home/joshu/mcp-{bc,ae,ams,renewable}` on the VM, each an
  independent docker-compose project.

## Live probes performed

### `mcp__project-docs-bc__list_tracked_projects`

Returned 5 projects. Shape per record:

```json
{
  "project_id": "bc-bluestown",
  "drive_folder_id": "1GEfwxz_5GG9zrpoUQwKq37yplvy5CG5V",
  "drive_folder_url": "1GEfwxz_5GG9zrpoUQwKq37yplvy5CG5V",
  "enabled": true,
  "last_sync_attempt": "2026-05-15 20:00:03.881129",
  "last_sync_success": "2026-05-15 20:00:28.174514",
  "last_sync_result": { "new": 0, "errors": [...], "failed": 3,
                        "deleted": 0, "modified": 0, "unchanged": 41,
                        "project_id": "bc-bluestown",
                        "total_in_drive": 44 },
  "created_at": "2026-04-28 03:59:31.464168"
}
```

Highlights from the probe:

- The tracked-projects record is exactly the shape versawiki's "tenant /
  source registration" record will want — folder pointer, enable flag,
  last-sync-attempt/success timestamps, structured last-sync-result.
- Sync results are persisted with `new / modified / unchanged / deleted /
  failed` counts plus a per-file error list. This is good telemetry —
  reuse the shape.
- The error list also exposes the *fragility* of the current pipeline.
  In `bc-honey-creek`'s last sync, 95 files failed; about a dozen with
  errors like `Database error: date/time field value out of range:
  "23/12/12"` (Postgres datestyle mismatch), one `[Errno -3] Temporary
  failure in name resolution`, and a long tail of `Unable to find the
  server at oauth2.googleapis.com` (transient DNS/network failure during
  the sync). Versawiki must (a) be far more robust on its date-parsing
  path, and (b) make Drive sync retry on transient network errors instead
  of marking files failed forever. **Failure-mode insight worth capturing.**
- One project (`bc-hossier-line`) is a misspelling of another
  (`bc-hoosier-line`) with the same `drive_folder_id`. Tenant IDs need
  validation; renaming or deduping needs first-class support.

### `mcp__project-docs-bc__list_document_types` (project_id=bc-bluestown)

Returned a fixed taxonomy of 10 types with counts:

```
contract:           13
specification:      23
letter:              1
email:               0
meeting_minutes:     0
rfi:                 2
submittal:          14
drawing:             6
design_calculation: 20
progress_report:     0
```

(`general_document` is in the schema but isn't returned by
`list_document_types` for this project — likely because the count is rolled
into the typed counts when classifier confidence is high enough; per the
troubleshooting notes the classifier in practice dumps most docs into
`general_document`.) The bluestown corpus is small (~80 files) and looks
unusually well-classified compared to what the troubleshooting notes
suggest is typical.

### `mcp__project-docs-bc__get_project_summary` (project_id=bc-bluestown)

Returns the same `document_types` block plus `open_rfis`, `pending_submittals`,
and a `recent_activity` array of `{type, id, preview}` records — the
preview is the first ~200 chars of the doc text. **Project-summary shape
is a clean candidate for the versawiki home-page-per-tenant data contract.**

### `mcp__renewable-knowledge__list_tracked_projects`

One "project" tracked — `engineering-rules` — pointing at a shared Drive
folder of codes/standards. Sync clean (7 new, 0 failed). The shared-
knowledge server is operated identically to the per-firm servers; the
"shared knowledge" semantics are entirely a matter of *what's ingested into
it*, not different code. Worth noting because versawiki's meta-MCP can use
the same approach: the meta layer isn't a different code path, just a
different corpus shape.

---

## Reusable patterns

### 1. Schema shape

From SKILL.md (verified against probes):

- One **table per document type** (`contract`, `specification`, `rfi`,
  `submittal`, `drawing`, `design_calculation`, `letter`, `email`,
  `meeting_minutes`, `progress_report`, `general_document`) with type-
  specific columns (e.g. RFIs have a `question`, contracts have parties,
  drawings have a sheet number).
- A **single `document_embeddings` table** holding chunks + vectors for
  semantic search, one row per chunk, joined back to the typed table by
  `(document_type, document_id)`.
- A **`projects` table** as the tenancy boundary inside a single server.
- **`rel_*` join tables** for cross-document references (e.g.
  `rel_contract_related_specs`, `rel_rfi_related_spec`).

This is a defensible starting schema. For versawiki:

- The typed-table-per-document-type is **debatable**. It gives clean
  per-type columns but adds friction every time the taxonomy changes
  (which, given M1's LLM-induced ontology, will happen). My recommendation
  is to keep a unified `documents` table with a `document_type` column and
  a `JSONB extras` blob for type-specific fields, then promote frequently
  queried extras into proper columns over time. Avoids schema migrations
  on every ontology update.
- The chunk + embedding split is exactly right; reuse as-is, with HNSW
  index (the prior MCPs predate HNSW being default in pgvector — they
  likely use IVFFlat or no index).
- The `projects` table maps cleanly to versawiki's `tenants`. The
  `project_id` filter pattern (every query scoped by `project_id`) maps
  cleanly to versawiki's tenant isolation, but at the row level only —
  see Multi-tenant isolation below.
- The `rel_*` tables are useful but their *meaning* is hand-coded
  (contract-spec, rfi-spec). Versawiki's ontology induction will produce
  *novel* relationship types per tenant; we should design relations as a
  single polymorphic table with a `relation_type` column from the start,
  not 10 hand-coded `rel_*` tables.

### 2. Ingestion pipeline stages

Inferred from the runbook + the failure surface:

```
Drive walk → file download → mime-type / extension dispatch →
text extraction (PDF / docx / xlsx / pptx parsers) →
document classifier (filename + content heuristics) →
write typed row → chunk text → embed → write embeddings →
extract cross-references → write rel_* rows.
```

Stages worth carrying forward verbatim:

- **`list_drive_folder` as a dry-run before any write.** Lets the user
  preview what would be ingested. Versawiki should keep this — for
  local folders, web UI, and Drive alike.
- **Sync result is structured: `new / modified / unchanged / deleted /
  failed / errors`.** Build the API around this from day one.
- **Per-file isolation:** one corrupt PDF doesn't kill the sync; it
  becomes a row in `errors[]` and the rest continues.
- **Detached background sync** (the `docker exec -d` workaround in the
  runbook). Confirms a hard requirement: **long-running ingestion must
  not block MCP request handling.** Versawiki should design this in from
  the start as a job queue, not a workaround.

Stages that need to change:

- **The classifier underperforms** — most files land in `general_document`
  (troubleshooting entry #11). Versawiki replaces this with the LLM-
  driven approach in `ontology.md`.
- **Date parsing is brittle.** Many `bc-honey-creek` failures are date-
  format issues from OCR/extraction. Versawiki should make every type-
  specific field tolerant of malformed values (store the raw string,
  parse opportunistically, never fail the whole document because one
  field doesn't parse).
- **Retry policy is too aggressive.** Transient `oauth2.googleapis.com`
  DNS failures mark files failed *for that sync*; they need to be
  retried on the next sync, not abandoned. Versawiki's job queue should
  classify errors as `permanent` vs `retryable`.

### 3. MCP tool surface

The 14 tools the prior MCPs expose are a good *minimum* surface for
versawiki's per-tenant MCP. Roughly grouped:

- **Ingestion:** `sync_from_drive`, `ingest_document`, `ingest_directory`,
  `list_drive_folder`, `register_project`, `unregister_project`,
  `incremental_sync_project`, `sync_all_tracked`, `list_tracked_projects`,
  `update_document`.
- **Query:** `search_documents`, `build_context`, `get_document`,
  `find_related_documents`, `find_by_reference`, `trace_document_chain`.
- **Insight:** `list_document_types`, `get_project_summary`,
  `build_document_generation_context`.

For versawiki, the *ingestion* tools are mostly server-internal — the
customer doesn't ingest via the MCP; the SaaS does. The customer-facing
MCP surface is closer to the *query* + *insight* set above, plus a
handful of new tools versawiki adds:

- `get_wiki_page(page_id)` — fetch a pre-compiled wiki page.
- `list_pages_by_topic(topic)` — navigate the emergent hierarchy.
- `propose_ontology_edit(...)` — let the LLM suggest taxonomy changes
  that the human reviews.
- `register_query_feedback(query_id, cited_doc_ids, was_useful)` —
  feeds the query-driven re-indexing loop.

### 4. Operational lessons

From the troubleshooting reference, things versawiki should bake in from
day one:

| Prior pain | Versawiki design choice |
|---|---|
| Firewall rule in wrong GCP project | Infra-as-code; environment manifests prevent stray manual rules |
| Firewall open to internet (no auth) | MCP servers gate on API key from day one — no "firewall as only line of defense" |
| Drive credentials mounted as directory not file | Avoid bind-mount-of-single-file pattern; mount secrets via the cloud secret manager |
| Missing env var for credentials path | Strict env validation at startup; refuse to start if required env is missing |
| `asyncio.run()` inside running event loop | Async-first codebase; CI lints `asyncio.run` calls |
| 60-second MCP client timeout | Every potentially long tool returns a `job_id`; poll via `get_job_status` |
| VM too small for ingestion | Ingestion runs in worker pool that scales horizontally; not on the MCP server |
| DB containers don't restart automatically | All managed Postgres (Cloud SQL / Supabase / RDS), not docker-compose Postgres |
| SSH disconnect kills `docker exec` | No interactive ops; everything is jobs in a queue |
| Service-account key pasted in chat | Secrets only reachable via env vars or secret-manager APIs; never read via `cat`/`head` |
| Classifier under-classifies | LLM-driven classification, with confidence; route low-confidence to `unclassified` not `general_document` |

---

## What versawiki *must* change vs the prior MCPs

The prior MCPs are a single-operator, single-machine setup. Versawiki is a
multi-tenant SaaS with a meta-learning layer. The structural changes:

### A. Multi-tenant isolation

Prior MCPs isolate by `project_id` *column* within a database. That works
for one operator but is the wrong primitive for B2B SaaS:

- **One database per tenant** (logical-DB-in-shared-cluster pattern; Postgres
  schemas are an option, separate databases are safer). Cross-tenant queries
  are *impossible* by construction, not just by query convention. Pattern
  reviewed in [Hamade — Architecting Secure Multi-Tenant Data
  Isolation](https://medium.com/@justhamade/architecting-secure-multi-tenant-data-isolation-d8f36cb0d25e),
  [AWS Prescriptive Guidance — Multi-tenant SaaS authorization](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-api-access-authorization/introduction.html).
- Per-tenant MCP endpoint URL (`/api/v1/<tenant-slug>/mcp` or per-tenant
  subdomain). Pattern: [Manikandan — Multi-Tenant MCP
  Servers](https://medium.com/@manikandan.eshwar/multi-tenant-mcp-servers-why-centralized-management-matters-a813b03b4a52),
  [Novumlogic — multi-tenant SaaS with MCP](https://www.novumlogic.com/blog/build-a-dynamic-multi-tenant-saas-platform-with-ai-agents-and-a-custom-mcp-server-client).
- Tenant ID embedded in *every* request at the gateway, not derived from
  query parameters or trusted client headers. Pattern: [Prefactor — MCP
  Security for Multi-Tenant AI Agents](https://prefactor.tech/blog/mcp-security-multi-tenant-ai-agents-explained).

### B. API-key authentication on the MCP itself

Prior MCPs rely on IP allow-listing (firewall to Josh's home IP). That
won't scale and isn't secure for a customer-facing product.

- Per-tenant API keys, scoped to read/write/admin permissions.
- Short-lived tokens preferred where MCP clients support OAuth — but the
  ecosystem is mixed; API keys are the lowest-common-denominator and
  Anthropic/Claude Desktop's `mcp-remote` works with header auth.
  ([MCP Authentication explained](https://www.getmaxim.ai/articles/mcp-authentication-explained-oauth-api-keys-and-token-management/))
- Key rotation, revocation, audit log per call. Standard SaaS hygiene.

### C. Self-improving meta-MCP

Brand-new surface, no analogue in the prior code. The shape:

- A server with no per-customer corpus of its own.
- Reads anonymised *patterns* from each tenant's MCP: ontology shape,
  query patterns, common failure modes, recurring relationship types.
- Writes back skills/markdown notes capturing "how to organise *this kind*
  of corpus."
- New tenants in a known domain get the meta-MCP's accumulated
  recommendations during onboarding.

Relevant prior art for the "self-improving agent" half:

- [Self-Evolving Agents with reflective and memory-augmented abilities —
  arXiv 2409.00872](https://arxiv.org/html/2409.00872v1)
- [MemSkill — learning and evolving memory skills, arXiv
  2602.02474](https://arxiv.org/pdf/2602.02474),
  [MemSkill GitHub](https://github.com/ViktorAxelsen/MemSkill)
- [Memento-Skills — Let Agents Design Agents, arXiv
  2603.18743](https://arxiv.org/pdf/2603.18743)
- The Anthropic [self-improving-agent skill](https://mcpmarket.com/tools/skills/self-improving-agent)
  pattern (use `.learnings/` markdown notes as durable memory).

The hardest design constraint: *no bytes from Tenant A may ever land in
Tenant B's view*. Solutions to study before M7:

- Differential-privacy noise on aggregate counts.
- LLM-summarised patterns reviewed by a curator agent before promotion.
- Hash-based "shape signatures" of ontologies that don't leak entity names.

Flagged in `notes/researcher.md` because the privacy bar is high enough
that a wrong call here is hard to walk back.

### D. Public-facing API + clients

Prior MCPs serve Claude Desktop via `mcp-remote`. Versawiki serves humans
on web/desktop/mobile *and* LLMs via MCP. Implications:

- HTTP/JSON API for human clients in addition to the MCP transport.
- WebSocket / SSE for live ingestion progress.
- Authentication shared between HTTP and MCP surfaces (one key works on
  both).
- The prior MCPs' SSE-over-HTTP transport is fine for MCP; nothing to
  change there.
- An MCP **gateway** in front of the per-tenant servers is the right
  abstraction at scale (rate limiting, audit, key management).
  ([Integrate.io — Best MCP Gateways
  2026](https://www.integrate.io/blog/best-mcp-gateways-and-ai-agent-security-tools/),
  [MintMCP — 7 top MCP gateways 2026](https://www.mintmcp.com/blog/enterprise-ai-infrastructure-mcp))

### E. Cross-platform clients

- **Web:** primary surface. Architect's choice on framework.
- **Desktop (M3):** Tauri (per the roadmap) running the ingestion path
  locally for paranoid corpora. The local-folder code path must be
  identical whether running in SaaS workers or in a Tauri sidecar.
- **Mobile (M5):** read-only viewer + chat.

The prior MCPs have *no* UI — Claude Desktop is the UI. Versawiki has UI
on every platform.

### F. Self-managed Postgres → managed Postgres

The prior setup runs Postgres inside docker-compose on the same VM as the
MCP server. The troubleshooting log records two real outages caused by DB
containers not restarting after a VM reboot, and the classifier under-
classification problem is partly because Postgres is treated as a write-
only sink that the operator never inspects.

Versawiki should use **managed Postgres** with point-in-time recovery
from day one, and tier the per-tenant databases in a shared cluster (one
cluster per ~100 tenants, sized accordingly). Pattern:
[DanubeData — pgvector RAG on managed Postgres,
2026](https://danubedata.ro/blog/pgvector-rag-managed-postgres-2026).

### G. Connectors over time

The prior MCPs do Drive only (plus local-folder via `ingest_directory`).
Versawiki's roadmap is local → Drive → OneDrive/SharePoint → Dropbox/Box
→ iCloud. The right abstraction is a *connector interface*:

```python
class Connector(Protocol):
    def list_files(self, scope) -> Iterable[FileRef]: ...
    def fetch(self, ref: FileRef) -> bytes: ...
    def watch(self, scope, callback) -> WatchHandle: ...
```

The prior MCPs' Drive connector code is the seed; everything else slots
behind the interface.

---

## What we still need from Josh's earlier GitHub repo

To do a real code audit and decide what to lift line-by-line, we'd want
visibility into:

- **Language and framework.** The skill mentions Python (`server.py`,
  `tools/drive_sync.py`, `parsers/drive_connector.py`) and async via
  `asyncio`. Confirm: is this FastAPI? Pure ASGI? Some MCP-server SDK
  (mcp-server-python)? Knowing the framework decides whether we extend
  or rewrite.
- **`docker-compose.yml`** for one of the stacks — concrete service
  definitions, env variables, image tags, port mapping. Useful for
  replicating the dev env locally.
- **`schema/` directory** — DDL for the typed tables, embeddings table,
  rel_ tables, projects table. The exact column shapes for each type
  (what's on a `contract` vs an `rfi`).
- **`parsers/`** — the file-type handlers (PDF, docx, xlsx, pptx). These
  are the slowest things to rebuild from scratch and likely the most
  reusable verbatim.
- **`tools/`** — implementation of each of the 14 MCP tools. Want to
  know how `search_documents` blends vector + keyword (is it a hybrid
  query, a reranker, pure pgvector?), how `build_context` assembles its
  RAG prompt, how `find_related_documents` works.
- **`parsers/drive_connector.py`** — the Drive sync logic; the
  troubleshooting notes already revealed bugs in it (`asyncio.run()` in
  async context), so we know it's the right file to find.
- **Document classifier code** — likely under `parsers/` or `classifiers/`.
  Want to see what heuristics it uses so we know what to replace.
- **Any tests.** If the prior repo has tests, that's a head start. If not,
  test-from-scratch is a big chunk of versawiki's M1 work.
- **Embedding model / API in use.** Stored in env vars; the dimension of
  the `vector` column in the schema will tell us which model.
- **`requirements.txt` / `pyproject.toml`.** Locks the exact library
  versions; useful to vendor or pin in versawiki.

Filename patterns we'd grep for: `**/server.py`, `**/tools/*.py`,
`**/parsers/*.py`, `**/schema/*.sql`, `**/docker-compose.yml`,
`**/Dockerfile`, `**/requirements.txt`, `**/pyproject.toml`.

When Josh hands over the repo, the Researcher should re-open this file
and append a "code audit" section against the items above. For now, this
document captures the architecture and patterns; the code is a separate
pass.

---

## Bottom line

The prior MCPs are a working blueprint for **single-operator Drive-to-RAG
with a Postgres-and-pgvector backend**. Versawiki inherits roughly 70% of
the *shape*: the ingestion pipeline stages, the schema split (chunks +
typed-doc + rel tables), the MCP tool surface, the sync-result data
contract, and most importantly the *list of failure modes* documented in
the troubleshooting notes — which is a free testing checklist for the
versawiki ingestion engineer.

The remaining 30% is the structural difference between *Josh's personal
second brain* and *a multi-tenant product*: multi-DB isolation, API-key
auth, managed Postgres, a job queue instead of `docker exec -d`, the
connector abstraction, an LLM-driven classifier instead of the brittle
keyword one, and the meta-MCP that has no prior-art analogue at all.

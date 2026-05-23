# Prior-art MCP code worth reusing

Ticket: **M0-05** (live-probe pass) + **M0-06** (real-code audit).
Latest: **M0-06**, 2026-05-22 by Researcher.

---

## M0-06: Real code audit (2026-05-22)

Source: `C:\Users\joshu\Downloads\project-mcp-server` — 20 Python files,
config + Dockerfile + docker-compose, no tests, no `.env*`, no embeddings
code (the `document_embeddings` table is stored but the `embedding BYTEA`
column is never written — search is pure `ILIKE`). The repo is a single-
operator, single-tenant snapshot of the project-docs-* family.

### File-by-file audit

| Path | Lines | Purpose (1 sentence) | REUSE / ADAPT / REPLACE | Why |
|---|---|---|---|---|
| `server.py` | 459 | MCP entry: 14 Tool declarations + stdio/SSE transport + raw `psycopg2.connect` per call. | REPLACE | Stdio + handcrafted SSE; no auth, no tenant resolution, no API keys, no streamable-HTTP, no connection pool. M1-BE-05 owns the replacement. Keep only the 14 tool *names + schemas* as a starter surface. |
| `manage.py` | 105 | CLI for `migrate / show-schema / ingest / info`. | ADAPT | Pattern (one entrypoint with subcommands) is fine; rewrite as `typer` CLI under `services/api/cli.py`, swap `psycopg2` for `asyncpg`, swap project_id for tenant slug. M1-BE-03 / M1-BE-01. |
| `schema/__init__.py` | 1 | Re-exports `load_config`, `apply_schema`, `generate_full_schema`. | REPLACE | Trivial; new module under `services/api/db/` exposes Alembic-equivalents. |
| `schema/manager.py` | 202 | YAML-driven CREATE TABLE / ALTER TABLE generator (table-per-doc-type + rel_ tables). | REPLACE | Replaced by Alembic + per-schema migration runner (M1-BE-03). Versawiki uses unified `documents` + `chunks` + polymorphic `relations` (DECISIONS.md), not table-per-type. **Lift the YAML approach as a future ontology config knob** — see Surprise #2 below. |
| `parsers/__init__.py` | 1 | Empty (no re-exports). | REPLACE | Trivial; new package init under `services/ingestion/parsers/`. |
| `parsers/base_parser.py` | 117 | `BaseParser` ABC + `ParseResult` dataclass + SHA-256 file hash. | REUSE | Clean abstraction; no tenant logic; the `(extract_text, extract_fields, detect_relationships) -> ParseResult` shape is exactly versawiki's connector-fed pipeline. Lift to `services/ingestion/parsers/base.py`. |
| `parsers/pdf_parser.py` | 298 | `pdfplumber` text + table extraction + scanned-PDF OCR fallback via `pytesseract`; plus three keyword-regex specialist subclasses (`Specification`, `Contract`, `Rfi`). | ADAPT | Keep the *PDF extraction core* (pdfplumber + OCR fallback) and extract it as a pure text+tables function. **Drop the keyword-regex specialist subclasses** — they're exactly what the M1 LLM classifier (M1-ING-03) replaces. AEC discipline keyword map gets lifted into the AEC starter taxonomy seed. |
| `parsers/docx_parser.py` | 224 | `python-docx` text + tables + headings + core-properties, plus `MeetingMinutes` / `Letter` regex specialists, plus legacy `.doc` via `antiword` subprocess. | ADAPT | Same as PDF: keep the docx extraction core (incl. heading-as-markdown and table-as-`[TABLE]` blocks — useful), drop the specialist regex subclasses. `.doc` shellout to `antiword` works but is fragile — flag for replacement with `mammoth`/`docx2txt`. |
| `parsers/excel_parser.py` | 115 | `openpyxl` text-flattening per sheet + CSV path + helpers (`get_sheet_names`, `get_sheet_as_dicts`). | REUSE | Tight, no tenant logic, useful helpers. Lift verbatim minus the `ScheduleExcelParser` AEC-specific subclass. |
| `parsers/email_parser.py` | 153 | `.eml` via stdlib `email` + `.msg` via `extract_msg` + attachment listing + thread-id from headers. | REUSE | Self-contained, useful, no tenant logic. Lift verbatim. |
| `parsers/registry.py` | 163 | Three-tier parser selection (explicit type / filename regex / extension fallback) + filename-detector statics. | ADAPT | Keep the *three-tier selection pattern* and the extension-map. **Drop the filename regex detectors** — they're a primitive classifier replaced by M1-ING-03. The "explicit type" override path stays useful for human-corrected documents. |
| `parsers/drive_connector.py` | 283 | Google Drive service-account client: list (recursive), download with Workspace-doc export, sync-folder driver. | ADAPT | Lift wholesale into `services/ingestion/connectors/gdrive.py` for M2. Adapt: (a) move secrets out of file-path env vars into Secrets Manager refs, (b) replace the embedded `asyncio.run()` (line 230) — it's *exactly* the bug called out in troubleshooting, (c) replace the "is this already ingested?" `ILIKE %{filename}%` query with the proper `content_hash`-based check, (d) make it conform to the `Connector` Protocol from M1-ING-01. |
| `tools/__init__.py` | 0 | Empty marker. | REPLACE | Trivial. |
| `tools/search.py` | 203 | `search_documents` (per-type-table ILIKE loop), `get_document`, `list_document_types` + a `_get_date_field` helper. | REPLACE | Per-type-table loop assumes table-per-type which we're not doing. The `_get_date_field` priority list is data we can keep. Vector + keyword hybrid search is M1-BE-05 + M1-ING-02. |
| `tools/cross_reference.py` | 279 | `find_related_documents` (rel_ table introspection + reverse-table introspection + text-mention search), `trace_document_chain` (DFS to depth 5), `find_by_reference` (per-type identifier-field map). | ADAPT | Pattern is gold — three-pass retrieval (explicit rels + reverse rels + text mentions) is what we want — but the SQL is table-per-type. Rewrite against the unified `documents` + polymorphic `relations` table. The identifier-field map and depth-5 DFS are reusable parameter choices. |
| `tools/ingest.py` | 269 | `ingest_document` (parse → insert into typed table → store rels → chunk to `document_embeddings`), `ingest_directory` (recursive `rglob`), `update_document`, `_store_text_chunks` (paragraph-grouped, ~1000-char chunks, no overlap). | ADAPT | Chunking strategy (paragraph-grouped to ~1000 chars) is decent but **no chunk overlap** and **no embedding step** — both are M1-ING-02. The `field_overrides` pattern and `update_document` shape are reusable. The `_serialize_value(json.dumps for list/dict)` and per-doc commit-or-rollback are the right shape. |
| `tools/drive_sync.py` | 79 | Thin MCP-tool wrappers calling `DriveConnector.sync_folder` / `list_folder`. | REPLACE | Trivial wrappers; once the Connector interface lands (M1-ING-01) these become generic. |
| `tools/context_builder.py` | 418 | `build_context` (purpose-driven gather plan over document types, keyword-scored chunk selection), `build_document_generation_context` (RFI/letter/spec/email lookups), `get_project_summary` (counts + open RFIs + recent activity). | ADAPT | **Purpose-driven gather plans are valuable** — keep the taxonomy of purposes (`question_answering`, `document_generation`, `status_summary`, `impact_analysis`) and the per-purpose document-type weights as a config knob. Rewrite the implementation: replace per-type table queries with ontology-node-scoped searches, replace keyword-score chunk selection with vector + hybrid (M1-ING-02 / M1-BE-04). |
| `config/__init__.py` | 0 | Empty marker. | REPLACE | Trivial. |
| `config/document_types.yaml` | 502 | YAML-defined taxonomy: 10 document types, 80+ fields, 25+ relationships, file-pattern hints. | ADAPT | **This is the AEC starter taxonomy** (DECISIONS.md 2026-05-22 says we lift it). Convert to versawiki's `ontology_nodes` seed format: each YAML `document_types.<X>.fields` becomes JSONB schema hints on an `ontology_nodes.metadata` column. Relationships become typed entries in the polymorphic relation table. Lift to `services/ingestion/seeds/aec_starter_taxonomy.yaml`. |
| `utils/__init__.py` | 0 | Empty marker. | REPLACE | Trivial; nothing in utils. |
| `requirements.txt` | 28 | `mcp>=1.0.0`, `psycopg2-binary`, `pdfplumber`, `python-docx`, `openpyxl`, `pyyaml`, `extract-msg`, Google API libs; OCR & embedding deps commented out. | ADAPT | Useful as a starting set for `services/ingestion/parsers/`. Drop `psycopg2-binary` (we use `asyncpg`), drop top-level `mcp` (different transport). Add `pgvector`, `pdfplumber`'s OCR siblings, FastAPI, RQ. **Uncomment the embedding deps + actually use them.** |
| `Dockerfile` | 15 | Python 3.12-slim + antiword + pip install + `CMD python server.py`. | ADAPT | Pattern OK; multi-stage for size + non-root user + healthcheck + `EXPOSE` belongs in versawiki's image. |
| `docker-compose.yml` | 39 | Postgres 16 + mcp-server containers, both with `postgres/postgres` credentials and host-port-exposed DB. | REPLACE | Single-tenant single-instance Postgres + plaintext default creds + 5432 exposed to host. We use managed Postgres (Neon, per DECISIONS.md). Local dev compose belongs but with secrets via `.env` and no port exposure to host outside dev. |
| `deploy/SETUP_GUIDE.md` | 220 | GCP VM bring-up runbook (gcloud commands, firewall rules, service account). | REPLACE | All of this is the prior `35.226.25.117` VM. Versawiki targets Fly.io + Neon + Cloudflare R2 (DECISIONS.md). The runbook is useful only as a checklist of "things ops needs to think about" — copy that to `notes/qa.md` if useful. |
| `deploy/drive-credentials.json` | 13 | Service-account creds stub. | REPLACE | Secrets stay out of repo (decided by DECISIONS.md). Gitignore. |
| `deploy/setup-gcloud.ps1` / `.sh` | 244 / 171 | GCP project + VM provisioning scripts. | REPLACE | GCP-specific; out of scope. |
| `README.md` | 220 | Doc + quick start. | REPLACE | Versawiki has its own README. |

### Bucket sizes

- **REUSE: 3 files** — `parsers/base_parser.py`, `parsers/excel_parser.py`, `parsers/email_parser.py`.
- **ADAPT: 10 files** — `manage.py`, `parsers/pdf_parser.py`, `parsers/docx_parser.py`, `parsers/registry.py`, `parsers/drive_connector.py`, `tools/cross_reference.py`, `tools/ingest.py`, `tools/context_builder.py`, `config/document_types.yaml`, `requirements.txt`, `Dockerfile`. (11; counting Dockerfile here.)
- **REPLACE: 13 files** — `server.py`, `schema/manager.py`, `schema/__init__.py`, `tools/__init__.py`, `tools/search.py`, `tools/drive_sync.py`, `config/__init__.py`, `parsers/__init__.py`, `utils/__init__.py`, `docker-compose.yml`, `deploy/*` (3), `README.md`. (Empty `__init__.py` files counted because they're real files even if trivially regenerated.)

### What we definitely keep (REUSE bucket)

1. **`parsers/base_parser.py`** — `BaseParser` ABC + `ParseResult` dataclass + SHA-256 helper. The interface is exactly what `services/ingestion/parsers/` needs.
2. **`parsers/excel_parser.py`** — `openpyxl` flatten-to-text + CSV path + the `get_sheet_as_dicts` helper. No tenant logic, no auth, no DB writes; lift wholesale (minus the `ScheduleExcelParser` AEC subclass).
3. **`parsers/email_parser.py`** — `.eml` + `.msg` extraction + attachment listing. Standalone, useful, lifts cleanly.

### What we adapt (ADAPT bucket)

1. **PDF extraction core from `parsers/pdf_parser.py`** — `pdfplumber` text + table extract + OCR fallback. Drop the keyword-regex specialist subclasses.
2. **DOCX extraction core from `parsers/docx_parser.py`** — text + heading-as-markdown + table-as-`[TABLE]` blocks. Replace legacy `.doc` `antiword` shellout with `mammoth`.
3. **`parsers/registry.py`** — three-tier selection (explicit type / filename / extension) is the right *pattern*; lose the filename regex detectors.
4. **`parsers/drive_connector.py`** — wholesale lift for M2 connector; fix the `asyncio.run`-inside-async bug; swap dedup-by-filename `ILIKE` for content-hash; conform to `Connector` Protocol.
5. **Three-pass relation pattern from `tools/cross_reference.py`** — explicit rels + reverse rels + text mentions. Rewrite SQL against unified table.
6. **Chunking pattern from `tools/ingest.py`** (paragraph-group to ~1000 chars) — keep, add chunk overlap, add embedding step.
7. **Purpose-driven gather plans from `tools/context_builder.py`** — taxonomy of purposes + per-purpose document-type weights as config.
8. **`config/document_types.yaml`** — the AEC starter taxonomy. Convert to ontology-node seed format.
9. **`manage.py`** subcommand-CLI pattern — rewrite as `typer`.
10. **Dockerfile** — pattern, with multi-stage + non-root + healthcheck added.
11. **`requirements.txt`** — starting set of parsing libs; drop `psycopg2`+`mcp`, add `pgvector`/`fastapi`/`rq`.

### What we replace (REPLACE bucket)

| File(s) | Why | M1 ticket |
|---|---|---|
| `server.py` | No auth, no tenant resolution, no API keys, stdio-or-handcrafted-SSE transport. Versawiki is per-tenant API-key-gated streamable-HTTP MCP. | **M1-BE-05** (MCP endpoint), **M1-BE-02** (auth middleware) |
| `schema/manager.py`, `schema/__init__.py` | Table-per-document-type with auto-CREATE/ALTER; versawiki uses unified `documents` + polymorphic relations with Alembic migrations. | **M1-BE-03** (schema provisioner) |
| `tools/search.py` | Pure `ILIKE`, no vectors, per-type-table loop. Versawiki is hybrid vector+keyword over unified table. | **M1-BE-05** (MCP `search` tool), **M1-ING-02** (embeddings) |
| `tools/drive_sync.py` | Drive-specific MCP wrappers; once `Connector` Protocol exists, source-agnostic. | **M1-ING-01** (connector interface) |
| Empty `__init__.py` files (parsers, tools, config, utils, schema) | Trivial; replaced with proper module setup. | (any) |
| `docker-compose.yml` | Single-tenant Postgres in-container, plaintext default creds. Versawiki uses managed Postgres (Neon). | **M1-BE-01** (FastAPI skeleton dev compose) |
| `deploy/*` (GCP runbook + creds + setup scripts) | GCP-specific; versawiki targets Fly.io / Neon / R2. | (M2+ ops tickets) |
| `README.md` | Already replaced. | (n/a) |

### Surprises (vs the M0-05 live-probe inference)

1. **No auth code exists at all.** Not even IP-allowlist logic in Python — IP allow-listing is *entirely at the GCP firewall layer*. The `server.py` connects to the DB with hardcoded-default `postgres/postgres` creds via env vars. The M0-05 doc inferred "IP-allowlist auth" as a *security model* — true at the infra layer — but at the code layer **there is no auth surface to swap out, only one to add**. That means we don't have to "remove" auth from the code; we build it net-new for versawiki. The replace bucket got smaller and the add bucket got bigger.

2. **The `document_embeddings` table exists but no embeddings are stored or used.** The schema declares `embedding BYTEA` (line 114 of `schema/manager.py`), the `_store_text_chunks` function in `tools/ingest.py` inserts only `chunk_text` and never populates `embedding`, and `requirements.txt` has `sentence-transformers` and `numpy` *commented out*. Search is pure `ILIKE %query%`. **The live MCPs are vector-RAG in name only; the prior code is keyword-search RAG.** This is a big deal: M0-05 assumed we'd inherit a working embedding pipeline; we don't. M1-ING-02 is more truly net-new than expected. The `document_embeddings` table is structurally a chunks table, useful as a precedent for the unified `chunks` table, but the *behaviour* is a stub.

3. **The schema is generated at runtime from YAML, not authored as SQL DDL.** `schema/manager.py` reads `config/document_types.yaml` and emits `CREATE TABLE` statements per type plus `ALTER TABLE ADD COLUMN` migrations on every startup. This is *more* dynamic than the M0-05 inference suggested. Two implications: (a) "schema-as-config" is a usable future feature — per-tenant ontology evolution could drive schema additions through a similar config layer, although versawiki's better answer is JSONB extras on a unified `documents` table; (b) **migrations are not tracked anywhere** — there is no Alembic, no SQL files, no version history. Schema drift between deployments is silent. M1-BE-03 must do proper Alembic from day one.

4. **Per-tenant Postgres role pattern doesn't exist.** The DB user is `postgres` superuser. Belt-and-braces tenant isolation by Postgres role (DECISIONS.md, §4.4) is net-new work, not an adapt.

5. **Chunking has no overlap and chunk size is 1000 chars** (line 233 of `tools/ingest.py`). Chunk overlap is standard practice for RAG; we get to set this correctly from the start.

6. **The `find_related_documents` text-reference pass uses `ILIKE`** on the entire `full_text` of every other document type, no LIMIT on the union, no index. This is a perf cliff at scale. M1 should use the embedding-based retrieval path for this and treat the `ILIKE` fallback as a last resort.

7. **`drive_connector.sync_folder` calls `asyncio.run(ingest_document(...))` from inside what's already an async-driven call path** (server.py → drive_sync.py → DriveConnector.sync_folder). This is the *exact* bug called out in the M0-05 troubleshooting catalogue and it's still in the code. Lifting this file requires fixing it.

8. **No tests of any kind.** No `tests/` directory, no `pytest.ini`, no fixtures. The "free test checklist" from the troubleshooting catalogue (M0-05) is genuinely all we have to go on. M1-QA-01 is fully net-new.

9. **No `.env` example, no Pydantic settings.** Env-var reading is scattered `os.environ.get(...)` calls with hardcoded defaults at each site. Versawiki should use `pydantic-settings` with a single `Settings` class.

10. **`google-api-python-client` is sync.** The connector uses the sync HTTP client even though the surrounding code is `async`. For M2 we should evaluate `aiogoogle` or accept the run-in-threadpool overhead.

### Recommended file lifts (next code session)

For each, the diff plan is one sentence:

1. **`parsers/base_parser.py`** → `services/ingestion/parsers/base.py`. *Diff:* swap `project_id` references in `ParseResult.to_db_row` for `tenant_id` + `source_id` keys; otherwise verbatim.

2. **`parsers/excel_parser.py`** → `services/ingestion/parsers/excel.py`. *Diff:* drop the `ScheduleExcelParser` subclass; otherwise verbatim.

3. **`parsers/email_parser.py`** → `services/ingestion/parsers/email.py`. *Diff:* verbatim.

4. **PDF extraction core** (extract `PdfParser.extract_text` + `_try_ocr` + `extract_tables` from `parsers/pdf_parser.py`) → `services/ingestion/parsers/pdf.py`. *Diff:* drop `SpecificationPdfParser`, `ContractPdfParser`, `RfiPdfParser` subclasses; keep the OCR-fallback threshold at 50 chars; move the AEC discipline keyword dict into the AEC seed taxonomy file.

5. **DOCX extraction core** (extract `DocxParser.extract_text` + `get_metadata` from `parsers/docx_parser.py`) → `services/ingestion/parsers/docx.py`. *Diff:* drop `MeetingMinutesDocxParser` + `LetterDocxParser`; replace the `antiword` shellout with `mammoth`.

6. **`parsers/drive_connector.py`** → `services/ingestion/connectors/gdrive.py` (M2 lift, not M1). *Diff:* (a) make it implement the `Connector` Protocol from M1-ING-01, (b) remove the embedded `asyncio.run(ingest_document(...))` — `sync_folder` should yield `FileRef`s or push jobs to the queue, not call ingestion directly, (c) replace the "already ingested?" `ILIKE %filename%` check with content-hash lookup, (d) read creds from Secrets Manager not file path.

7. **`config/document_types.yaml`** → `services/ingestion/seeds/aec_starter_taxonomy.yaml`. *Diff:* rename top-level key from `document_types` to `ontology_nodes_seed`; map each type's `fields` to JSONB schema hints; map `relationships` to typed entries with a `relation_type` discriminator.

8. **Parser-selection three-tier pattern from `parsers/registry.py`** → `services/ingestion/parsers/registry.py`. *Diff:* keep tiers (explicit type / extension fallback); replace tier 2 (filename regex) with a call into the LLM classifier (M1-ING-03); keep the extension map.

9. **Chunking function `_store_text_chunks` from `tools/ingest.py`** → `services/ingestion/chunker.py`. *Diff:* add 10-15% overlap between chunks; emit `(text, ordinal, metadata)` tuples for the embedding worker to consume rather than inserting directly; respect `tiktoken` token counts rather than char counts.

10. **Purpose-driven gather plan from `tools/context_builder.py` (the `_get_gather_plan` dict)** → `services/api/context/gather_plans.py`. *Diff:* keep the four purposes and the per-purpose document-type weighting; rewrite the search calls to use ontology-node filters + vector retrieval; expose plans as overridable config.

11. **Three-pass relation algorithm from `tools/cross_reference.py`** → `services/api/relations/finder.py`. *Diff:* rewrite SQL against unified `documents` + polymorphic `relations` table; keep the depth-5 BFS in `trace_document_chain`; keep the identifier-field priority list as data.

12. **`manage.py` subcommand pattern** → `services/api/cli.py` using `typer`. *Diff:* every subcommand takes `--tenant <slug>` instead of `project_id`; `migrate` runs Alembic against the tenant schema.


## M0-05: Live-probe inference (2026-05-22) — superseded by M0-06 above

*Original M0-05 doc preserved below for traceability. Where M0-06 (above) contradicts M0-05, M0-06 wins.*

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

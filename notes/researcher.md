## 2026-05-22 — M0-06 real code audit (prior MCP-server repo)

Audited every file in `C:\Users\joshu\Downloads\project-mcp-server` (20
Python files + Dockerfile + compose + requirements + config YAML + GCP
runbook). Full file-by-file table, bucket sizes, surprises, and the
recommended file-lift list are at the top of
`docs/research/prior-art.md` under "M0-06: Real code audit (2026-05-22)".

### Buckets

- **REUSE: 3** — `parsers/base_parser.py`, `parsers/excel_parser.py`,
  `parsers/email_parser.py`.
- **ADAPT: 11** — including `parsers/pdf_parser.py`, `parsers/docx_parser.py`,
  `parsers/registry.py`, `parsers/drive_connector.py`,
  `tools/cross_reference.py`, `tools/ingest.py`, `tools/context_builder.py`,
  `config/document_types.yaml`, `manage.py`, `Dockerfile`, `requirements.txt`.
- **REPLACE: 13** — `server.py`, the schema generator, search.py, drive_sync.py,
  empty `__init__.py`s, docker-compose, all of deploy/, README.

### Top surprises (vs the M0-05 live-probe inference)

1. **No auth code at all.** The prior MCPs are firewall-only; there is
   nothing in the Python to remove or swap. Versawiki adds auth net-new.
2. **`document_embeddings` is a stub.** The table exists; the `embedding
   BYTEA` column is never written; search is pure `ILIKE`. The prior
   MCPs are vector-RAG in name only. M0-05 over-credited them. M1-ING-02
   is more genuinely net-new than I had assumed.
3. **Schema is generated from YAML at runtime, no Alembic, no SQL history.**
   Migrations happen silently on `CREATE TABLE IF NOT EXISTS` +
   `ALTER TABLE ADD COLUMN` at server startup. No version tracking.
4. **`drive_connector.sync_folder` literally contains the bug from the
   troubleshooting catalogue** (calls `asyncio.run(ingest_document(...))`
   from an async context). Lift requires fixing.
5. **Chunking has no overlap; 1000-char chunks by char count, not tokens.**
   We can set this correctly from day one.

### Flags for Josh (none day-or-two-rework; just visibility)

- The `parsers/drive_connector.py` lift for M2 needs to address (a) async
  bug, (b) dedup by content-hash not filename, (c) secrets via
  Secrets Manager not file path. All flagged in the recommended-lift table.
- Replacing `antiword` (legacy `.doc`) with `mammoth` is a small library
  choice; I called it without escalating.
- The "schema-as-config" YAML approach is an *unexpectedly* tempting
  future direction for per-tenant ontology evolution. I noted it as a
  possibility in the surprise section but did not recommend pursuing it
  — versawiki's JSONB-extras-on-unified-table answer is better. Flag
  here in case the Architect sees it differently.

### What's now ready for the next code session

The recommended-file-lifts table in `prior-art.md` (item 5 of the M0-06
section) lists 12 concrete lifts with one-sentence diff plans each.
Ingestion engineer can start from that table; Backend engineer's
`server.py` replacement (M1-BE-05) doesn't need any of these lifts.

---

_Researcher's working notes. Newest at top._

## 2026-05-22 — first research wave (M0-03, M0-04, M0-05)

Worked the three M0 research tickets in parallel against web search and the
live `mcp__project-docs-*` tools. Outputs:

- `docs/research/landscape.md` — competitor survey, ~13 products + summary
  table + "where versawiki can win".
- `docs/research/ontology.md` — schema induction, hierarchical embedding
  clustering, LLM-driven taxonomy, query-driven re-indexing, plus a
  recommended M1 pipeline.
- `docs/research/prior-art.md` — runbook + live probes against the four
  domain-expert MCPs, what to reuse, what to change, what we still need
  from Josh's earlier repo.

All claims in the survey + ontology files have markdown links to sources.
The prior-art file names the two MCP tools I probed
(`mcp__project-docs-bc__list_tracked_projects`,
`mcp__project-docs-bc__list_document_types`,
`mcp__project-docs-bc__get_project_summary`, and
`mcp__renewable-knowledge__list_tracked_projects`) and includes their raw
output shapes.

### Headline takeaways

1. **The "wiki structures itself" pitch is uncrowded.** Competitors are
   either federated search/chat (Glean, Onyx, Dash) or human-authored
   wikis with AI bolted on (Notion, Confluence, Coda, Guru). The closest
   neighbour to versawiki is the niche OSS project LLM-Wiki, which is
   single-user. See landscape.md "Cross-cutting observations" and "Where
   versawiki can win."
2. **Per-tenant MCP as a first-class product surface is open ground.**
   Guru is the only mainstream product shipping MCP and it's gated behind
   Enterprise.
3. **The right M1 ontology pipeline is `BERTopic-grounded -> LLM-proposed
   types -> entity graph + community detection -> pre-materialised wiki
   pages -> query-driven re-indexing`.** Details and citations in
   ontology.md "Recommended approach for versawiki M1."
4. **Reuse ~70% of the prior MCPs' shape; replace ~30%.** Inherit the
   ingestion stages, the chunks+typed+rel schema split, the MCP tool
   surface, and the troubleshooting catalogue (it's a free test
   checklist). Replace tenant isolation, auth, the classifier, Postgres
   ops, and add the meta-MCP. Details in prior-art.md. **NOTE (M0-06):**
   the 70/30 split was true at the *pattern* level but the actual code
   reuse is closer to 3 files lift / 11 adapt / 13 replace — see M0-06
   audit above. The patterns survive; the implementations mostly don't.

### Flagged questions (day-or-two-rework stakes — Josh / Architect needs to call these)

These three are the ones where a wrong choice now would cost a rework I
think justifies escalation under the AGENTS.md rule:

**F-01. Embedding model selection.** Changing the embedding model later
invalidates every stored vector and requires a full corpus re-embed. The
choice constrains the desktop variant (M3) — if we pick an API-only model,
desktop ingestion needs network for every chunk. My recommendation:
pick a model with a self-hostable open-weights variant
(`nomic-embed-text-v2` is the leading candidate; Voyage v3 if API-only is
fine). **Architect should lock this in DECISIONS.md before any code is
written.** *(Resolved 2026-05-22: dim=1024 locked, model fluid, OpenAI
3-large@1024 in M1, self-hostable swap before M3.)*

**F-02. GraphRAG inline vs reimplement.** GraphRAG (Microsoft's reference
impl) does entity extraction + community detection well but is heavyweight
and opinionated about prompts. We can pull in their pipeline directly
or reimplement the bits we need. Tradeoff: inline = faster to M1 demo,
slower to customise; reimplement = slower to M1 demo, owns the prompts
end-to-end. My lean is *reimplement*, because we'll need our own
prompts for the meta-MCP anyway. **Architect call.** *(Resolved
2026-05-22: reimplement.)*

**F-03. Meta-MCP cross-tenant privacy mechanism.** The meta-MCP's
core claim — *learn shapes across tenants without sharing bytes* — is
load-bearing for the product positioning. If the privacy mechanism (DP
noise on aggregates? LLM-summarised patterns + curator review? hash-based
shape signatures?) is wrong, the entire M7 value prop collapses. This
isn't an M1 blocker but the architecture for M1's instrumentation has
to anticipate it — *what we log per tenant determines what the meta-MCP
can learn later*. **Want Josh's read on the acceptable privacy bar
before Architect designs the M1 logging schema.** *(Resolved 2026-05-22:
content-vs-pattern split; principles may cross, content may not.)*

### Smaller calls I made without escalating

- **Default starter taxonomy.** Lift the prior MCPs' AEC taxonomy as the
  cold-start default; the LLM induction replaces it on first ingestion.
  Cheap if wrong.
- **No graph DB in M1.** Postgres + pgvector + a polymorphic relation
  table covers it. We can migrate to Neo4j later if the joins get
  painful. Cheap if wrong.
- **No fine-tuning in M1.** Prompt + retrieval is competitive at this
  corpus size per the MDPI 2025 comparative study; we save the
  fine-tuning option for the meta-MCP, which actually has cross-tenant
  data to learn from.
- **HNSW over IVFFlat** in pgvector. 2026 best practice per several
  guides; the prior MCPs predate this default and we should set it
  correctly from the start.

### What I'd like back from the next session

- Josh to point us at the prior GitHub repo so the Researcher (or
  Architect) can do a real code audit. Filename patterns and what we
  need are listed in `docs/research/prior-art.md` "What we still need
  from Josh's earlier GitHub repo." *(Done 2026-05-22 — M0-06 audit above.)*
- Architect's decision on F-01 and F-02 above. F-03 can wait until M1's
  logging schema design. *(All resolved 2026-05-22.)*
- If the Architect's stack proposal (`docs/architecture/stack.md`) is
  written by next session, I'll review it against the M1 pipeline
  in ontology.md and flag any conflicts.

### Sources I leaned on most

(Full citations in each docs/research/*.md file. The standouts:)

- For the landscape: the GoSearch and Workativ pieces on Glean pricing,
  the Featurebase Guru pricing breakdown, the Onyx GitHub and the
  nashsu/llm_wiki repo.
- For ontology: Microsoft GraphRAG, BERTopic (the Pinecone tutorial is
  the cleanest walkthrough), TaxoGen (KDD 2018) for the recursive
  clustering pattern, TaxoAdapt (2025) for the evolving-corpus angle,
  the Springer 2025 "doubly-checked taxonomy induction" paper for the
  LLM verification idea.
- For prior-art: the `domain-expert-mcps` SKILL.md and its troubleshooting
  reference are the primary source; the multi-tenant MCP and managed-
  Postgres pieces backed the gap analysis.

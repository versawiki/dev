# Status

_Read this first. Updated by the Orchestrator at the end of every session._

## Last session summary

- **2026-05-23 overnight cron** — *no new commit by cron* — Picked M1-ING-03c off the top of the safe list; specialist completed it cleanly (225→230 in ingestion, +5 tests, all green). At push time discovered `origin/main` had advanced to `087a59c` with a functionally identical M1-ING-03c commit landed independently. Cron abandoned its `54ddb1b`, reset to `origin/main`, and pushed this BACKLOG/STATUS/notes bookkeeping fix instead. See `notes/orchestrator.md` top entry.
- **2026-05-23 overnight cron** — `227f5a2` — M1-ING-03b: Classifier retry on LLM 429/5xx (Anthropic + OpenAI providers, shared `_post_with_retries` helper, exponential backoff matching the embedder pattern). +10 tests in ingestion (215 → 225). All 582 tests green.
- **2026-05-23 follow-up** — `087a59c` — M1-ING-03c: catch-all annotation in classifier prompt (Anthropic + OpenAI providers, +5 tests in ingestion, 225 → 230). Landed independently of the overnight cron; cron detected the duplicate and stopped cleanly.

## Current milestone

**M1 — Local-folder ingestion (headless).** End-to-end loop closed in code. **587 tests passing** across four services. An ingested folder produces queryable wiki pages all the way through the system.

## Per-service current state

- `services/api/` — **129 tests** — Full M1 backend (auth + provisioner + query routes + MCP-over-HTTP + real pages route).
- `services/ingestion/` — **230 tests** (+5 from M1-ING-03c's catch-all annotation) — Connector + parsers + chunker/embedder + classifier (with 429/5xx retry + catch-all annotation in prompt) + ontology inducer + wiki page builder.
- `services/meta-mcp/` — **166 tests** — Privacy checkers + audit log + signature collector + meta-store + skill writer + skill applier.
- `services/support-agent/` — **62 tests** — Autonomous CS: KB, safe/forbidden actions, PII redaction, cross-tenant block, intake adapters, escalation queue.

## The end-to-end loop in code

```
LocalFolderConnector → Parsers → Chunker → EmbeddingProvider →
  ClassifierResult → OntologyInducer (BERTopic/Leiden fallbacks active) →
    PageBuilder → InMemoryPageStore →
      GET /v1/tenants/{tid}/pages/{pid} returns real page →
      MCP read_page tool returns real page
```

Plus the meta-MCP loop running orthogonally: signatures emit through privacy checkers → FileMetaStore → SkillWriter drafts → text-checker gate → skills/<domain>/...md → SkillApplier prepends learned text on next ingestion.

## Credentials on disk (gitignored)

- `.vw-cron-token` — GitHub PAT (for push)
- `.vw-anthropic-key` — for the classifier, taxonomy proposer, page writer, skill writer, support agent
- `.vw-openai-key` — for the embedding provider

All three protected by the `.vw-*` patterns in `.gitignore`; verified with `git check-ignore -v` after each write. NONE of them ever land in a commit, and they are NOT saved to my long-term memory.

## Overnight cron status

Still live. Safe list shrunk by one more (M1-ING-03c now Done via `087a59c`). Next fire's top pick: `M1-MCP-01a-fix`.

## Blockers awaiting Josh

- (none code-wise — every keys we have are in)
- Pending in your hands per the operations docs: Apple Developer signup, Florida LLC filing, OPS-04 (Claude Agent SDK on VM) decision

## Next interactive tickets (morning, in order of leverage)

1. **M1-QA-01 end-to-end smoke against a real corpus** — now possible with both keys + ING-05. Point it at the prior MCP repo's docs as a corpus and verify the whole pipeline produces pages.
2. **M1-CS-03/04 wire support agent to admin API + SMTP** — gets customer support actually functional.
3. **M1-MCP-05 opt-out API surface** — last meta-MCP ticket.
4. **OPS-04 Agent SDK orchestrator** when you're ready for the deployment work.

## Quick links

- `README.md`, `ROADMAP.md`, `BACKLOG.md`, `DECISIONS.md`, `AGENTS.md`, `ARCHITECTURE-LAYOUT.md`
- `docs/architecture/{stack,v1,domain-observation-v1}.md`
- `docs/research/{landscape,ontology,prior-art}.md`
- `docs/operations/*.md`
- `services/{api,ingestion,meta-mcp,support-agent}/`
- `notes/*` — per-role working logs

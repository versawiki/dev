# Versawiki — Tech Stack Recommendation (v0.1)

**Status:** Architect's recommendation. Pending Orchestrator review and lock-in to `DECISIONS.md`.

**TL;DR:** Python backend (FastAPI), Postgres with pgvector, Next.js web, Tauri desktop, Expo/React Native mobile, Redis-backed RQ workers, BAAI/`bge-m3` embeddings via a local inference service with OpenAI/Voyage as a hosted fallback. Deployed on Fly.io (per-tenant Postgres on Neon for tenant isolation; meta-MCP on a single shared host).

---

## Choices

### Backend language & framework — Python 3.12 + FastAPI 0.115

- The novel core of versawiki — classification, ontology induction, the self-improving meta-MCP — is ML/agent-flavored code. Python is where that ecosystem lives (transformers, sentence-transformers, instructor, pydantic-ai, dspy, langgraph, the Anthropic + OpenAI SDKs, llama-index components we may borrow).
- The four `project-docs-*` MCP servers Josh already runs are Python; the Researcher's M0-05 pass will likely confirm a meaningful reuse surface there. Picking Python now avoids a port.
- FastAPI gives us OpenAPI-by-default (cheap, typed client generation for web/desktop/mobile), native async, and Pydantic v2 models we can share with the ingestion code.
- **Tradeoff:** Python is slower than Go/Rust for pure I/O fanout (connector walking, chunk hashing). We accept this — the bottleneck is embedding + LLM latency, not Python overhead — and we will reach for a Rust sidecar only if the file walker becomes the hot path.
- **Tradeoff considered & rejected:** Node/TypeScript backend. Tempting because it unifies with the web stack, but loses ML ecosystem reach and would force the meta-MCP to live in a second language.

### Web framework — Next.js 15 (App Router) + React 19 + TypeScript 5.6

- Server components let us render heavy wiki pages cheaply and stream them, which matches the "ask the wiki, get a structured answer" UX better than a pure SPA.
- App Router's route handlers give us a clean place to put the per-tenant API-key auth proxy without standing up a second service.
- shadcn/ui + Tailwind for components — Josh hasn't asked for a custom design system, and shadcn lets the UI engineer move fast without owning a component library.
- **Tradeoff:** Next.js couples us to Vercel-isms (or careful self-hosting). Acceptable; if we self-host, Next is fine on Fly/Render.

### Desktop wrapper — Tauri 2.0

- Tauri ships a ~5MB binary versus Electron's ~80MB+ and uses the OS webview, which matters for a "private corpus, runs on my laptop" product where users will notice bloat.
- Tauri's Rust core gives us a clean place to embed a local ingestion worker for the M3 "don't send my files to the cloud" path — the same Python ingestion code can run as a sidecar via PyOxidizer or a bundled Python.
- The ROADMAP already names Tauri; this confirms it.
- **Tradeoff:** Smaller plugin ecosystem than Electron. We aren't doing exotic OS integrations, so this is fine.

### Mobile framework — Expo (React Native) SDK 52

- Mobile is read-only wiki + ask-the-wiki chat (M5). React Native lets us share TypeScript types, API client, and a chunk of UI primitives with the Next.js web app.
- Expo's managed workflow + EAS Build means the UI engineer doesn't have to babysit native toolchains for an app that has no native modules of substance.
- **Tradeoff considered & rejected:** Flutter. Faster animations, but forces a second UI language (Dart) and breaks the type-sharing story with web. Not worth it for a read-mostly app.

### Primary database — Postgres 16

- Multi-tenant relational data (tenants, users, API keys, documents, chunks, ontology nodes, query logs) is a textbook Postgres workload.
- Postgres 16 has solid JSONB, generated columns, and row-level security — all of which we use for tenant isolation (see `v1.md`).
- Managed via Neon (branchable, scale-to-zero, cheap per-tenant DBs) for production; plain Postgres in Docker for dev.
- **Tradeoff:** Neon's cold-start latency on a scaled-to-zero branch is ~300ms. For an LLM-facing MCP that's tolerable; we'll pin "hot" tenants to always-on if it ever bites.

### Vector store — pgvector 0.8 (in the same Postgres)

- Same DB, same transactions, same backup story. For our scale (a customer's document corpus, not the web), pgvector with HNSW indexes is fast enough and removes an entire piece of infrastructure.
- Lets us do hybrid queries trivially (vector similarity AND `ontology_node_id = X` AND `tenant_id = Y`) without a join across systems.
- **Tradeoff:** At ~10M+ chunks per tenant, a dedicated vector DB (Qdrant, LanceDB) starts to outpace pgvector on recall/latency. We accept this and will migrate per-tenant if any customer hits that scale. The chunk table schema is designed so the embedding column can become a foreign reference to an external vector DB without touching the rest of the model.

### Embedding model — BAAI/`bge-m3` (default), with provider fallback

- `bge-m3` is multilingual, supports dense + sparse + multi-vector retrieval, runs comfortably on a single GPU, and is open-weight (no per-token billing). Embedding dim 1024 — pgvector-friendly.
- We expose embeddings behind a thin `EmbeddingProvider` interface so we can swap to Voyage `voyage-3` or OpenAI `text-embedding-3-large` per tenant (some enterprise tenants will require no-self-hosted-models).
- **Tradeoff:** Self-hosting an embedder means we own a GPU (or pay for a small inference endpoint, e.g., Modal/Replicate). We accept the ops cost for cost predictability and to keep customer document content from ever leaving our infrastructure.

### Queue / workers — Redis 7 + RQ

- Ingestion (walk → chunk → embed → classify → upsert ontology) is a long, fan-out-able job. We need a job queue, not a streaming bus.
- RQ is small, Python-native, and supports priorities + scheduled jobs out of the box. Celery is more powerful and we don't need it.
- Redis doubles as our rate-limit and short-cache layer.
- **Tradeoff considered & rejected:** Temporal. Lovely durability semantics, but operational overhead is large for a team this small. RQ + idempotent jobs gets us 80% of the way for 10% of the cost.

### LLM access — Anthropic primary (Claude 4.x family), OpenAI secondary

- Classification, ontology induction, and the meta-MCP's "write yourself a skill" loop are reasoning-heavy. Anthropic's models are Josh's daily driver and the team is built on Claude — picking Anthropic for the primary path keeps eval loops fast.
- OpenAI secondary for cost-sensitive bulk classification (gpt-4o-mini) and for tenants who already have OpenAI contracts.
- All LLM calls go through a `LLMProvider` interface; per-tenant overrides allowed.

### Infrastructure / hosting — Fly.io (app tier) + Neon (DB tier) + Cloudflare R2 (blob)

- Fly gives us per-region app deployment without the AWS yak-shave. Important for the MCP endpoint: low latency between the LLM provider's region and our MCP service matters more than people expect.
- Neon for branchable, per-tenant Postgres (see auth section in `v1.md`).
- R2 for storing the original document blobs (so we can re-chunk without re-fetching from the customer's source). S3-compatible API, no egress fees — meaningful when an LLM agent might pull a source-of-truth document occasionally.
- **Tradeoff:** Fly outages have bitten people. We accept the risk in exchange for velocity; production hardening is an M2/M3 concern.

---

## Versions to pin (initial)

| Layer | Choice | Version |
|---|---|---|
| Python | CPython | 3.12 |
| Web framework | FastAPI | 0.115 |
| ORM | SQLAlchemy + Alembic | 2.0 / 1.13 |
| Validation | Pydantic | 2.9 |
| Worker | RQ | 2.0 |
| DB | Postgres | 16 |
| Vector | pgvector | 0.8 |
| Cache/queue | Redis | 7.4 |
| Web | Next.js / React / TS | 15 / 19 / 5.6 |
| UI kit | Tailwind / shadcn-ui | 4.x / latest |
| Desktop | Tauri | 2.0 |
| Mobile | Expo SDK | 52 |
| Embeddings | bge-m3 | latest snapshot |
| LLM SDKs | anthropic / openai | latest |

---

## What we are explicitly NOT picking now

- **A dedicated graph DB** (Neo4j, Memgraph). The ontology is a graph, but it's small and read-mostly; modeling it as adjacency rows in Postgres is plenty until a tenant has >100k ontology nodes. We will reach for AGE (Postgres graph extension) before adding a new system.
- **A search engine** (Elasticsearch, Meilisearch). pgvector + Postgres FTS covers our hybrid needs at this scale. Revisit at M3+.
- **Kubernetes.** No.

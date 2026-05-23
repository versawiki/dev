# Ontology induction for mixed-document corpora

Ticket: **M0-04**. Status: **draft v1**, written 2026-05-22 by the Researcher.

Versawiki's core promise is that the wiki *structures itself* from the
customer's documents. The novel work is in **automatically discovering the
right ontology** — categories, document types, entities, relationships —
without a per-customer template. This file surveys what's known about that
problem.

Headings follow the brief: (1) schema induction from text, (2) hierarchical
clustering of embeddings, (3) LLM-driven taxonomy proposal, (4) query-log-driven
refinement. Each section names the techniques, papers, and OSS to reuse. The
final section is a recommended approach for M1.

---

## 1. Schema induction from text (classical)

**The problem.** Given raw text with no schema, derive the entity types,
relationship types, and attribute types that describe what's in it. Distinct
from extraction-with-known-schema: here we're proposing the schema.

**Two foundational families:**

- **Open Information Extraction (OpenIE)** — extract `(subject, relation,
  object)` triples from sentences without a predefined relation vocabulary,
  then cluster the resulting relations into a schema. Surveyed at length in
  [Niklaus et al., *A Survey on Open Information Extraction*, COLING
  2018](https://arxiv.org/pdf/1806.05599) and the updated 2022 review
  ([Open Information Extraction: A Review](https://axi.lims.ac.uk/paper/2310.11644)).
  OPIEC is a canonical large-scale corpus
  ([Gashteovski et al., AKBC 2019](https://arxiv.org/pdf/1904.12324)).
- **Event/entity schema induction** — learn the slot structure of an event
  or entity type from many instances of it. Recent survey of LLM-empowered
  knowledge graph construction:
  [arXiv 2510.20345](https://arxiv.org/html/2510.20345v1).

**Why classical OpenIE alone is insufficient for versawiki.**
The triples it produces are syntactic, the canonicalisation problem
("Apple Inc." vs "Apple" vs "AAPL") is unsolved at scale, and the output is
a flat triple store, not a usable wiki ontology. Useful as a *signal source*
fed into clustering/LLM steps below.

## 2. Hierarchical clustering of embeddings

**The pattern (now standard).** Embed → reduce dimensions → cluster → label.

- **Embedding.** Sentence-transformer (or any modern embedding model) per
  chunk or per document. Already a settled best practice across the
  ecosystem. ([Pinecone — Advanced Topic Modeling with
  BERTopic](https://www.pinecone.io/learn/bertopic/))
- **Dimensionality reduction.** UMAP is the default; preserves
  neighbourhood structure better than PCA for clustering.
  ([BERTopic docs](https://bertopic.com/))
- **Clustering.** HDBSCAN is the default; density-based, doesn't require K
  upfront, assigns outliers to a noise cluster (cluster -1) instead of
  forcing them. Optional swap to agglomerative if you want a fixed
  hierarchy. ([BERTopic FAQ](https://maartengr.github.io/BERTopic/faq.html))
- **Hierarchy.** BERTopic supports hierarchical topic reduction post-cluster
  via cosine similarity between topic embeddings — produces a topic tree
  you can render in a wiki sidebar.
  ([Vaj — BERTopic with hierarchical clustering](https://vtiya.medium.com/bertopic-with-hierarchical-clustering-d781c9f66253),
  [BERTopic GitHub issue #2269](https://github.com/MaartenGr/BERTopic/issues/2269))
- **Labelling.** c-TF-IDF (BERTopic's default) gives keyword labels;
  pairing it with an LLM ("here are 20 docs in this cluster — name the
  topic in 3 words") gives human-readable labels for free.

**Foundational papers worth citing in the architecture doc:**

- [TaxoGen — Zhang et al., KDD 2018](https://arxiv.org/pdf/1812.09551) —
  unsupervised topic taxonomy construction by adaptive term embedding and
  clustering. Recursive: each cluster is re-embedded locally, then split
  again. Reference implementation:
  [franticnerd/taxogen on GitHub](https://github.com/franticnerd/taxogen).
- [TaxoAdapt — Wan et al., 2025](https://arxiv.org/pdf/2506.10737) —
  aligns LLM-based multidimensional taxonomy construction to evolving
  corpora; uses density-of-papers to decide which nodes to expand. Maps
  cleanly onto a versawiki use case where the corpus keeps growing.

**Why this is insufficient on its own for versawiki.** Clustering gives you
*topics*, not a *type system*. A folder of project docs clusters by topic
(electrical, civil, geotech) but versawiki needs to know that *this* doc is
a contract, *that* doc is a drawing, *that other* one is an RFI — different
*types*, even when they're about the same topic. Hence the next section.

## 3. LLM-driven taxonomy proposal

This is where the field is moving in 2025–2026. The shape:

1. **Sample.** Take a stratified sample of documents from the corpus
   (covering different file types, sizes, source folders).
2. **Inspect with an LLM.** For each sample doc, give the LLM the filename,
   first ~1000 chars, and any metadata; ask it to (a) classify into a type
   from a starter list, (b) propose new types if needed, (c) describe what
   "kind of corpus" this is.
3. **Aggregate.** Roll up the proposals into a unified taxonomy. Resolve
   synonyms (LLM does this well too). Output: an inferred type list +
   short description per type.
4. **Apply to the rest of the corpus** as a zero-shot classifier.

**Reference papers and projects:**

- [TaxoAdapt — Wan et al., 2025](https://arxiv.org/pdf/2506.10737).
- [Taxonomy Induction Using LLMs: Doubly-Checked Mechanism + Self-evaluation
  — Springer 2025](https://link.springer.com/chapter/10.1007/978-981-96-1809-5_11)
  — addresses the LLM hallucination problem in taxonomy generation by
  cross-checking proposed nodes against the source corpus.
- [Automated Taxonomy Construction Using LLMs: Fine-Tuning vs Prompt
  Engineering — MDPI 2025](https://www.mdpi.com/2673-4117/6/11/283) —
  comparative study; prompt engineering competitive with fine-tuning at
  much lower cost for moderate corpora.
- [LLMs4OL 2025 Overview](https://www.tib-op.org/ojs/index.php/ocp/article/download/2913/2922/52931)
  — workshop survey of where LLM-based ontology learning is in 2025.
- [LLM-empowered knowledge graph construction survey, arXiv
  2510.20345](https://arxiv.org/html/2510.20345v1) — broad map of the
  current literature, including hybrid LLM+embedding+graph approaches.
- [LLM Zero-shot Triple Extraction for Ontology Generation from Software
  Engineering Standards — arXiv 2509.00140](https://arxiv.org/html/2509.00140v2)
  — practical pipeline: assertion-led ABox/TBox coextraction.
- [ZeroDL — Zero-shot Distribution Learning for Text Clustering via LLMs,
  arXiv 2406.13342](https://arxiv.org/pdf/2406.13342) — interesting
  inversion: have the LLM describe how it *sees* the dataset, then use
  that meta-description to drive clustering.
- [Beyond Prompting (Sun et al., 2022) — Clustering Representations for
  Zero-shot Classification, arXiv 2210.16637](https://arxiv.org/pdf/2210.16637)
  — BGMM-over-embeddings; +20% absolute over pure prompt-based zero-shot.

**Production-grade OSS for the LLM-knowledge-graph angle:**

- [Microsoft GraphRAG](https://microsoft.github.io/graphrag/) — extracts an
  entity/relationship graph from raw text, runs community detection on it
  to produce a hierarchy, and pre-summarises each community. Ships as a
  pipeline; GraphRAG 2.0 (2025) tightened the knowledge-graph integration.
  ([Microsoft Research GraphRAG overview](https://www.microsoft.com/en-us/thesource-developer/Event/330/microsoft-graphrag),
  [DataCamp tutorial](https://www.datacamp.com/tutorial/graphrag),
  [Ailog GraphRAG 2.0 release notes](https://app.ailog.fr/en/blog/news/graphrag-2-microsoft))
- [LlamaIndex `PropertyGraphIndex`](https://docs.llamaindex.ai/en/stable/examples/property_graph/property_graph_basic/) —
  per-chunk `kg_extractors` attach entities and relations as metadata; can
  combine vector and graph retrieval. Less batteries-included than
  GraphRAG but more composable.
  ([LlamaIndex announcement post](https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms),
  [Neo4j Labs LlamaIndex guide](https://neo4j.com/labs/genai-ecosystem/llamaindex/))
- [Onyx (formerly Danswer)](https://github.com/onyx-dot-app/onyx) ships a
  document classification step but it's shallow — relies mostly on
  embeddings. Their gap is exactly the gap we want to fill.

**A practical pattern from the renewable-knowledge MCPs** (see
`prior-art.md`): they use a *fixed* canonical document-type taxonomy
(contract, specification, RFI, submittal, drawing, design_calculation,
letter, email, meeting_minutes, progress_report, general_document) hand-coded
for AEC documents. The classifier is keyword-based and underperforms — most
documents land in `general_document` even when filenames clearly signal the
type. Lesson: **the type system can be domain-specific without being
hard-coded — you induce it once per tenant/vertical, not once per
codebase.**

## 4. Query-log-driven refinement

**The premise.** A corpus that nobody asks calendar questions of doesn't
need a calendar view. A corpus that gets asked "where is X" twenty times a
week needs an X view.

**The classical literature:**

- **Query refinement, expansion, suggestion.** Decades of IR work;
  [TU Delft lecture deck](https://chauff.github.io/documents/ir2017/Query-Refinement-Lecture.pdf)
  is a good summary of the canonical techniques (Rocchio, pseudo-relevance
  feedback, query log mining for suggestions).
- **Click-through models.** Examination Hypothesis + cascade models infer
  relevance from clicks while controlling for position bias.
  ([Examination Hypothesis with Query-Specific Position Bias, arXiv
  1003.2458](https://arxiv.org/pdf/1003.2458),
  [Refining recency search with click feedback, arXiv
  1103.3735](https://arxiv.org/pdf/1103.3735))
- **Pseudo-relevance feedback and drift minimization** —
  [USPTO 11222277](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11222277).
- **General IR review.** [Optimization techniques in information retrieval —
  ScienceDirect 2025](https://www.sciencedirect.com/science/article/pii/S2772662225001134).

**Tunable in production today:**

- **Algolia dynamic faceting** — facets surfaced and ordered by query
  patterns, not fixed by the developer. Reference doc on the mechanism:
  [Algolia faceting](https://www.algolia.com/doc/guides/managing-results/refine-results/faceting),
  [Implementing dynamic faceting](https://www.algolia.com/blog/engineering/implementing-faceted-search-with-dynamic-faceting-with-code).
- **Elasticsearch Learning to Rank (LTR) plugin** — log feature values per
  query during search, train an offline LTR model, deploy back into the
  ranker. ([Elasticsearch LTR docs](https://elasticsearch-learning-to-rank.readthedocs.io/en/latest/),
  [Logging Feature Scores](https://elasticsearch-learning-to-rank.readthedocs.io/en/latest/logging-features.html),
  [Working with Features](https://elasticsearch-learning-to-rank.readthedocs.io/en/latest/building-features.html))
- **OpenSearch Learning to Rank** — fork/successor with similar workflow.
  ([AWS OpenSearch LTR docs](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/learning-to-rank.html))
- **Elastic — data-driven query optimization** — recent blog post on
  feeding click data back into ranking:
  [Elastic blog](https://www.elastic.co/blog/improving-search-relevance-with-data-driven-query-optimization).

**The shape for versawiki.** Treat every MCP query and every human query as
a labelled event (`query text`, `documents returned`, `documents the LLM
actually cited` or `documents the human clicked`). Periodically re-derive:

- which entities are most asked about → promote into the sidebar / nav
- which document types are most retrieved → re-rank in default views
- which cross-references the LLM follows → strengthen those edges
- which queries return nothing useful → flag for ontology refinement

This loop is light-weight in M1 (just log events, batch-process nightly)
and gets more sophisticated in later milestones.

---

## Recommended approach for versawiki M1

M1 is **local-folder ingestion, headless**, on a small-to-medium corpus
(thousands of files, not millions). Multi-tenant isolation is required but
each tenant is one folder. Per the constraints in `ROADMAP.md`, we want the
hard parts — classification, ontology induction, query-driven re-indexing —
exercised at a real-but-tractable scale.

The recommendation, in pipeline order:

### Step 1 — Parse and embed

- Walk the folder, parse each file with the appropriate extractor (PDF →
  `pdfplumber` or `pymupdf`; Office → `python-docx` / `openpyxl` /
  `python-pptx`; etc.). Reuse whatever the prior MCPs already do.
- Chunk text (~500 tokens, ~100-token overlap is the standard starting
  point; tune per-corpus later).
- Embed with a current sentence-transformer (or OpenAI/Anthropic embedding
  API — Architect should pick; the ontology pipeline is model-agnostic).
- Store chunks + embeddings in **pgvector** with HNSW index. Best practice
  in 2026 per [DanubeData](https://danubedata.ro/blog/pgvector-rag-managed-postgres-2026)
  and [DigitalApplied](https://www.digitalapplied.com/blog/build-self-hosted-rag-postgres-pgvector-tutorial-2026).

### Step 2 — Inferred type taxonomy (LLM-driven, BERTopic-grounded)

Two-stage, the ordering matters:

1. **Topic clustering for grounding.** Run BERTopic (UMAP → HDBSCAN → c-TF-IDF
   labels) over the embeddings to get an initial topic structure and a
   sense of what *clusters* exist. Cheap, deterministic, repeatable. Gives
   the LLM concrete material to look at in step 2.
2. **LLM-proposed type taxonomy.** Stratified sample: pick 5–10 docs from
   each cluster, plus the 20 largest docs, plus a random tail. For each
   doc, prompt the LLM with `filename + first 2000 chars + metadata` and
   ask: *"What type of document is this? Use a name from this starter list
   if it fits; propose a new name if none fit."* Aggregate the proposals,
   merge synonyms (LLM does this too), output a per-tenant type taxonomy.

Starter list (lifted from the prior MCPs because it's a decent neutral
starting point): `contract, specification, rfi, submittal, drawing,
design_calculation, letter, email, meeting_minutes, progress_report,
general_document`. Tenants whose corpora are unrelated to AEC will end up
with very different lists — that's the point.

The doubly-checked + self-evaluation mechanism from
[Springer 2025](https://link.springer.com/chapter/10.1007/978-981-96-1809-5_11)
is a near-future enhancement: have the LLM verify each proposed type by
re-classifying a held-out sample and flagging the types with low
self-consistency.

### Step 3 — Entity and relationship extraction

- Per-chunk entity extraction (NER + LLM-augmented for noisy outputs).
- Cross-chunk coreference: same-name entities in different documents are
  linked. Standard pipeline; [GraphRAG](https://microsoft.github.io/graphrag/)
  does this at production quality and is a candidate to inline.
- Relationship extraction: prompted LLM extraction over chunk pairs that
  co-mention entities. Bias toward fewer, higher-confidence edges.
- Store in Postgres as `entity`, `entity_mention`, `relation` tables —
  *not* in a separate graph DB unless the architect insists. Postgres
  + pgvector + a graph-style join table covers M1 needs and avoids a
  second store. (Postgres-only is also what the prior MCPs use; see
  `prior-art.md`.)

### Step 4 — Hierarchy via community detection

- On the entity graph, run Leiden / Louvain community detection
  (GraphRAG's approach) to produce a *hierarchy* of clusters.
- Summarise each community with a brief LLM call so the wiki has a
  human-readable label and overview per node.
- The hierarchy doubles as the wiki's navigation tree.

### Step 5 — Wiki materialisation

- For each `(entity, document-type)` cell with enough mass, generate a
  *wiki page* that summarises what we know. Pre-compute these — don't do
  on-demand RAG. This is the LLM-Wiki insight
  ([nashsu/llm_wiki](https://github.com/nashsu/llm_wiki)): the wiki is the
  pre-compiled artefact, not on-demand retrieval. Persistent wikis are
  also cheaper to serve via MCP than re-running RAG on every call.
- Pages are versioned; re-materialise on (a) corpus change above a
  threshold, (b) ontology change, (c) cron.

### Step 6 — Query-driven re-indexing loop

- Log every MCP query and every human query with: query text, ranked
  results returned, which results were cited (LLM) or clicked (human).
- Nightly batch:
  - Update per-entity demand score → promotes hot entities up the
    navigation tree.
  - Update per-edge demand score → reweights graph edges.
  - Detect queries with no good answer → flags ontology gaps for review.
  - Detect query clusters that consistently hit the same documents →
    these are candidate new *wiki sections* to materialise.
- Mechanism mirrors Elasticsearch LTR's feature-logging pattern
  ([ES LTR feature logging](https://elasticsearch-learning-to-rank.readthedocs.io/en/latest/logging-features.html))
  and Algolia's dynamic faceting
  ([Algolia](https://www.algolia.com/blog/engineering/implementing-faceted-search-with-dynamic-faceting-with-code)),
  adapted to a wiki context.

### What we are deliberately *not* doing in M1

- **No fine-tuning.** Prompt + retrieval beats fine-tuning at this corpus
  size for taxonomy proposal — backed by
  [the MDPI 2025 study](https://www.mdpi.com/2673-4117/6/11/283).
- **No graph DB.** Postgres + pgvector + relation tables is enough.
- **No cross-tenant pattern sharing yet.** That's M7 (the meta-MCP shape
  learning). M1 just instruments well so M7 has data to mine.
- **No multi-modal ingestion** beyond text-extraction-from-PDFs. Images,
  diagrams, video transcripts come later.

---

## Open questions flagged for Architect

Recorded here so the next pass can converge:

1. **Embedding model lock-in.** Switching embedding models later invalidates
   every stored vector. We should pick a model that's stable, locally
   runnable for the desktop variant, and not too expensive at API scale.
   Likely candidates: `nomic-embed-text-v2`, OpenAI `text-embedding-3-large`,
   Voyage v3. Architect decides; my recommendation is a model with a
   self-hostable open-weights variant so M3 (desktop) doesn't need an API
   call for every chunk.

2. **GraphRAG: inline vs reimplement.** GraphRAG is heavyweight (Microsoft
   Research codebase, lots of LLM calls per ingestion). Cheaper alternative:
   reimplement just the entity-extraction + community-detection bits in our
   own pipeline. Tradeoff: GraphRAG works out of the box but is opinionated
   about prompts/models. Architect decision.

3. **Where the LLM lives during ingestion.** Each ingestion step that
   calls an LLM (type taxonomy, entity extraction, page generation) needs a
   model endpoint. For the SaaS path, our API; for the desktop variant, a
   local model (Ollama/llama.cpp). The pipeline should treat the LLM as a
   pluggable adapter from day one or we'll regret it in M3.

4. **Whether to ship a v0 *type-system* before the LLM-driven induction
   runs.** Pro: gives a usable wiki on the very first sync, before any LLM
   work. Con: the prior MCPs' fixed taxonomy *under-classifies* most
   corpora (per `prior-art.md`). My take: ship with the AEC-flavoured
   starter taxonomy as a default and replace it with the LLM-induced one
   on first ingestion. Not a day-or-two-rework call; architect can decide.

Items (1) and (2) are day-or-two-rework calls and are escalated in
`notes/researcher.md`.

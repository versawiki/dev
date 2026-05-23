
## 2026-05-22 — M1-ING-02 chunker + embedder pipeline (net-new, complete)

`M1-ING-02` shipped fully net-new per the M0-06 audit. The prior
project-mcp-server had a `BYTEA` embedding column that was never written to
and `sentence-transformers` commented out in requirements; nothing to lift.

### New package layout under `services/ingestion/src/versawiki_ingestion/`

- `chunking/`
  - `base.py` — `ChunkSpec` (Pydantic v2 frozen), `normalize_text`,
    `compute_content_hash`. The single load-bearing invariant: the chunk's
    `content_hash` is sha256 of `normalize_text(chunk.text)`. Normalisation
    rules: NFC unicode + CRLF->LF + trailing-whitespace strip + collapse
    3+ blank lines to 2.
  - `text_splitter.py` — `RecursiveCharacterSplitter(chunk_size=1500,
    chunk_overlap=200)`. Hierarchy: `("\n\n", "\n", ". ", " ", "")`. Three
    explicit idempotency tests pin the gating property.
  - `code_splitter.py` — `CodeSplitter` placeholder; wraps the recursive
    splitter with `chunk_size=2000`. Tree-sitter swap is ING-04.
  - `chunker.py` — `Chunker` picks between text/code by extension or MIME.
- `embedding/`
  - `base.py` — `EmbeddingProvider` Protocol; `EMBEDDING_DIM = 1024` (single
    source of truth). Signature:
    `async def embed(self, texts: list[str]) -> list[list[float]]` +
    `dimension: int` + `provider_name: str` instance attrs.
  - `openai_provider.py` — `OpenAIEmbeddingProvider`. Reads `OPENAI_API_KEY`
    lazily at first `embed()` call. POSTs to `/v1/embeddings` with
    `dimensions=1024` (Matryoshka). Batches 100. Exponential backoff
    (1s, 2s) on 429/5xx; max 3 attempts; non-retryable 4xx raises
    immediately. Accepts an injected `httpx.AsyncClient` and `sleep` hook
    so tests don't touch the network or wall clock.
  - `stub_provider.py` — `StubEmbeddingProvider`: sha256-derived 1024-dim
    deterministic vectors for tests.
  - `registry.py` — `get_embedding_provider(name, settings)`. Names today:
    `"openai"`, `"stub"`. `"bge-m3"` / `"nomic"` raise `NotImplementedError`
    as M3 placeholders.
- `pipeline/`
  - `models.py` — `IngestionJob`, `ChunkRecord`, `EmbeddingRecord`.
    `ChunkRecord.with_embedding(vec, name)` validates `len(vec) ==
    EMBEDDING_DIM` before returning the copy.
  - `process_document.py` — top-level coroutine. Idempotency on
    `known_hashes: set[str]`: doc-level sha256 of raw bytes; if known,
    returns `[]`. Otherwise: parse via the existing parser registry ->
    chunk -> embed batch -> attach embeddings -> emit `ChunkRecord`s.
  - `worker.py` — `InProcessQueue` (test-only) + `enqueue_ingest` +
    `run_job`. RQ stays abstracted behind a `_Queue` Protocol so the Redis
    impl plugs in later without touching call-sites.

### Deps added

- `httpx>=0.27,<1` in `pyproject.toml`. (Already in the FastAPI/asyncio
  stack; just promoted to a runtime dep of ingestion for the OpenAI
  provider.) No `openai` SDK; calling the REST API directly avoids the
  SDK's retry overrides.

### Tests added under `services/ingestion/tests/`

- `test_chunking.py` — 22 tests: three explicit idempotency tests,
  chunk_size honored, overlap honored, hierarchical fallback (paragraph ->
  line -> sentence -> word -> char), empty-input -> [], whitespace-only ->
  [], validation rejects `chunk_overlap >= chunk_size` and non-positive
  `chunk_size`, Chunker selector picks code-splitter for `.py`.
- `test_embedding_stub.py` — 9 tests: dim attribute, determinism, distinct
  inputs -> distinct vectors, empty input -> empty output, Protocol
  compliance, registry resolution + unknown name + future-provider
  `NotImplementedError`.
- `test_embedding_openai.py` — 13 tests, all mocked via a
  `FakeAsyncClient` (no respx in the env; injected client suffices).
  Covers: `dimensions=1024` in payload, batches at 100 (201 inputs ->
  3 calls), retry on 429 + then 200, retry through 502+500 + then 200,
  exhaustion after 3 retries raises with status in message, non-retryable
  4xx raises immediately, missing key raises at first call (not at
  import), env var path, dim-mismatch rejection, count-mismatch rejection,
  empty input -> zero HTTP calls.
- `test_pipeline_process_document.py` — 4 tests: multi-chunk + embedding
  attach, known-hash short-circuit -> [], empty text -> [], chunk_hash +
  embedding idempotency across two runs.
- `test_worker_inprocess.py` — 4 tests: enqueue returns job_id and stores,
  runner gets `(job, payload)`, full round-trip via process_document,
  missing-job raises `KeyError`.

### Test pass count

```
cd /sessions/dazzling-intelligent-thompson/mnt/versawiki/services/ingestion
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vwpyc PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -q tests/
```

```
90 passed in 0.91s
```

(40 existing + 50 net-new.)

### One small note for BE-03

`ChunkRecord` is the cross-package contract. When BE-03 wires up SQLAlchemy,
the column shape from `docs/architecture/v1.md` §2 maps 1:1 except for the
`token_count` column, which we deliberately omit from `ChunkRecord` until a
tokenizer is selected (out of scope for M1-ING-02). BE-03 can compute it at
persistence time using whatever tokenizer the embedding provider declares.

---

_Ingestion & ontology engineer's working notes. Newest at top._

## 2026-05-22 — M1-ING-01 tests written (session entry)

Finished `M1-ING-01` by adding the three test files the prior specialist
hadn't gotten to. Source files were already in good shape — no signature
changes required, no source bugs found.

Files added under `services/ingestion/tests/`:

- `test_local_folder_connector.py` — covers `list()` (recursive walk, ref
  fields), `fetch()` (exact bytes, path-traversal refusal), constructor
  validation, and three `watch()` scenarios (initial ADDED for existing
  files, ADDED for a file written after `watch()` starts, MODIFIED + DELETED
  detection). `watch()` is driven via `anyio.move_on_after` so a hung
  generator can't lock the suite. Pytest's `asyncio_mode = "auto"` (set in
  `pyproject.toml`) means no explicit `@pytest.mark.asyncio` is needed.
- `test_parsers.py` — smoke tests for `GeneralTextParser` (plain text +
  `file_hash` determinism), `EmailParser` (headers, body, ISO date,
  attachment listing) against the `sample_eml` fixture, and `ExcelParser`
  (multi-sheet extraction, `get_sheet_names`, `get_sheet_as_dicts`) against
  `sample_xlsx`. Excel tests are guarded with
  `@pytest.mark.skipif(importlib.util.find_spec("openpyxl") is None, ...)`
  so CI without openpyxl skips rather than imports-erroring.
- `test_registry.py` — parametrised tests covering all three resolution
  tiers (`for_type`, `for_mime`, `for_extension`), case-insensitivity, plus
  `for_path` and `for_ref` precedence (explicit_type > mime > extension).
  Includes the three MIME types the M1-ING-01 ticket called out
  (`text/plain`, the xlsx OOXML MIME, `message/rfc822`) and the rest of the
  registered set.

### Sandbox notes

- All runtime deps (`pydantic`, `anyio`, `structlog`, `openpyxl`,
  `python-magic`, `extract-msg`) were available in the Linux sandbox; no
  tests are currently being skipped on this machine. The `@skipif` on the
  Excel tests is a safety net for stripped CI containers.
- `python-magic` is installed, so the connector's `_mime_guess` calls
  `magic.from_file` first. For very short text files magic classifies them
  as `application/octet-stream`, which is fine — `mime_type` is documented
  as a best-guess hint and not load-bearing for identity. The test
  intentionally does not over-assert on the exact MIME string.
- One transient quirk: pytest's `tmp_path` cleanup hit a
  `RecursionError` in `shutil.rmtree` while tearing down the modified-file
  watch test on this filesystem. It does not affect pass/fail — the test
  itself succeeds and the recursion is in the post-test cleanup, which
  pytest tolerates. Worth flagging to QA if it surfaces on real CI.

### Result

```
40 passed in 0.69s
```

No source files were modified. No git activity.

---


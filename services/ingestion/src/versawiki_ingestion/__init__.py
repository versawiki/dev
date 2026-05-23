"""Versawiki ingestion service.

Public surface:

- `connectors.base.Connector` — Protocol for source adapters.
- `connectors.local_folder.LocalFolderConnector` — M1 default.
- `parsers.base.BaseParser` / `ParseResult` — parser ABC + result dataclass.
- `parsers.registry.ParserRegistry` — MIME/extension -> parser resolution.
- `chunking.Chunker` / `RecursiveCharacterSplitter` — text splitting for embedding.
- `embedding.EmbeddingProvider` / `OpenAIEmbeddingProvider` / `StubEmbeddingProvider`
  — embedding-model abstraction; 1024-dim locked via `EMBEDDING_DIM`.
- `pipeline.process_document` — connector -> parser -> chunker -> embedder.

See `services/ingestion/README.md` and `docs/architecture/v1.md` §1.1.
"""

__version__ = "0.1.0"

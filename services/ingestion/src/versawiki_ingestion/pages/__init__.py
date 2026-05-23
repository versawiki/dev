"""Wiki page builder — turns induced ontology + chunks into readable pages.

This is the last link in the ingestion chain:

  Connector -> Parser -> Chunker+Embedder -> Classifier -> OntologyInducer
                                                                    |
                                                                    v
                                                              PageBuilder
                                                                    |
                                                                    v
                                                              PageStore
                                                                    |
                                                                    v
                                                           API + MCP read_page

A *wiki page* is one materialised, summarised view of an ontology node's
chunks. We build pages **stale-on-event**: every page carries `is_stale`
and `version`; the page builder writes a fresh page on first ingest, the
ingestion-event bus flips `is_stale=True` when something underneath the
page changes (new chunk, deleted chunk, re-induced ontology), and the
next reader gets a background rebuild (the stale page is served
immediately so reads never block).

Public surface:

- ``WikiPage``, ``PageBuildJob`` — Pydantic models.
- ``PageBuilder`` — async builder; one call per ontology node.
- ``PageBuildPipeline`` — walks a full `OntologyTree` and emits pages.
- ``LLMPageWriter`` Protocol; ``AnthropicPageWriter`` / ``OpenAIPageWriter``
  / ``StubPageWriter`` impls.
- ``PageStore`` Protocol; ``InMemoryPageStore`` impl plus the
  ``PostgresPageStore`` signature (real impl in BE-04-followup).
- ``mark_stale_on_event`` — the staleness hook the event bus calls.
"""

from .builder import PageBuilder
from .llm_writer import (
    AnthropicPageWriter,
    LLMPageWriter,
    OpenAIPageWriter,
    StubPageWriter,
)
from .models import PageBuildJob, WikiPage
from .pipeline import PageBuildPipeline
from .staleness import StalenessEvent, mark_stale_on_event
from .store import InMemoryPageStore, PageStore, PostgresPageStore

__all__ = [
    "AnthropicPageWriter",
    "InMemoryPageStore",
    "LLMPageWriter",
    "OpenAIPageWriter",
    "PageBuildJob",
    "PageBuildPipeline",
    "PageBuilder",
    "PageStore",
    "PostgresPageStore",
    "StalenessEvent",
    "StubPageWriter",
    "WikiPage",
    "mark_stale_on_event",
]

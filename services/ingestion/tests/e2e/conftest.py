"""Shared fixtures for the end-to-end smoke test.

This fixture materialises a small synthetic corpus on disk, walks it with
``LocalFolderConnector``, runs every ref through ``process_document`` with
fully-stubbed providers, then drives ``OntologyInducer`` + ``PageBuildPipeline``
to produce the final ``WikiPage`` list. The whole bundle is module-scoped so
the (still cheap) pipeline only runs once per test session.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import openpyxl
import pytest
import pytest_asyncio

from versawiki_ingestion.chunking import Chunker, RecursiveCharacterSplitter
from versawiki_ingestion.classification import (
    DocumentClassifier,
    StubLLMClassifier,
)
from versawiki_ingestion.classification.base import ClassifierResult
from versawiki_ingestion.classification.taxonomy import Taxonomy
from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
from versawiki_ingestion.embedding import StubEmbeddingProvider
from versawiki_ingestion.ontology.inducer import OntologyInducer
from versawiki_ingestion.ontology.models import OntologyTree
from versawiki_ingestion.pages import (
    InMemoryPageStore,
    PageBuildPipeline,
    PageBuilder,
    StubPageWriter,
)
from versawiki_ingestion.pages.models import WikiPage
from versawiki_ingestion.parsers.registry import ParserRegistry
from versawiki_ingestion.pipeline import ProcessedDocument, process_document
from versawiki_ingestion.pipeline.models import ChunkRecord


SMOKE_TENANT_ID = "smoke-tenant"
SMOKE_SOURCE_ID = "smoke-source"
OTHER_TENANT_ID = "other-tenant"


# ----------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------


def _build_synthetic_corpus(root: Path) -> None:
    """Materialise 5-10 files on disk under ``root``.

    Mix of .txt, .eml, .xlsx. At least one RFI-shaped file (so the stub
    classifier picks `rfi`), at least one meeting-minutes file, and one
    tiny single-line file so the rollup-into-parent path exercises.
    """
    # 1. RFI-shaped .txt - enough text for >=2 chunks.
    rfi_body = (
        "RFI 042 - concrete mix design clarification.\n\n"
        + (
            "submitted_by Jane Doe; assigned_to structural team; "
            "response pending review by the design engineer of record. "
        )
        * 80
    )
    (root / "rfi_042.txt").write_text(rfi_body, encoding="utf-8")

    # 2. Second RFI .txt - different number, same shape.
    rfi_body_2 = (
        "RFI 057 - rebar spacing question.\n\n"
        + (
            "submitted_by Bob Smith; assigned_to structural team; "
            "awaiting structural engineer of record response. "
        )
        * 70
    )
    (root / "rfi_057.txt").write_text(rfi_body_2, encoding="utf-8")

    # 3. Meeting minutes .txt.
    minutes_body = (
        "Meeting Minutes - Weekly Coordination Call.\n\n"
        + "Attendees: Alice, Bob, Carol, Dave. "
        + "Agenda: schedule review, action items, next steps. "
        + (
            "Action item: review the structural drawings before next "
            "meeting; Decision: proceed with the revised concrete pour "
            "schedule discussed in last week's coordination meeting. "
        )
        * 60
    )
    (root / "minutes_2026_05_15.txt").write_text(minutes_body, encoding="utf-8")

    # 4. Second meeting minutes file - different week.
    minutes_body_2 = (
        "Meeting Minutes - Owner Architect Contractor Coordination.\n\n"
        + "Attendees: project manager, superintendent, owner rep. "
        + (
            "Agenda item discussed: open RFIs, change order log, "
            "schedule float. Action item: respond to all open RFIs "
            "by end of week. Decision: pull schedule forward two days. "
        )
        * 60
    )
    (root / "minutes_2026_05_22.txt").write_text(minutes_body_2, encoding="utf-8")

    # 5. RFC-822 email (.eml). Body is padded out so chunking produces
    #    multiple chunks (the chunker uses chunk_size=400).
    eml_body_padding = (
        "We will go over the project schedule, the open RFI log, and the "
        "upcoming structural pours. Please bring the latest drawing set "
        "and the RFI tracker. The agenda is roughly: project schedule "
        "walkthrough, open RFI review, structural pour planning, action "
        "items and next steps. "
    ) * 12
    eml = (
        "From: alice@example.com\n"
        "To: bob@example.com, carol@example.com\n"
        "Cc: dave@example.com\n"
        "Subject: Project kickoff next Monday\n"
        "Date: Mon, 12 May 2026 09:30:00 -0400\n"
        "In-Reply-To: <thread-001@example.com>\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Hi all,\n\n"
        "Quick heads-up that the kickoff meeting is at 10am Monday in the "
        "conference room. "
        + eml_body_padding
        + "\n\nThanks,\nAlice\n"
    )
    (root / "kickoff.eml").write_text(eml, encoding="utf-8")

    # 6. .xlsx RFI log.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RFI Log"
    ws.append(["RFI Number", "Title", "Status", "Submitted By", "Assigned To"])
    ws.append(["RFI-001", "Conduit routing question", "responded", "Jane", "Electrical"])
    ws.append(["RFI-002", "Concrete mix design", "under_review", "Bob", "Structural"])
    ws.append(["RFI-003", "Rebar spacing in slab", "open", "Alice", "Structural"])
    ws.append(["RFI-004", "MEP coordination clash", "responded", "Dave", "MEP"])
    ws.append(["RFI-005", "Storefront curtain wall detail", "open", "Carol", "Architect"])
    ws2 = wb.create_sheet("Notes")
    ws2.append(["section", "comment"])
    ws2.append(["general", "Updated weekly by the project engineer."])
    ws2.append(["general", "All RFIs require a response within 7 calendar days."])
    wb.save(root / "rfi_log.xlsx")

    # 7. Tiny one-line .txt - exercises the rollup-into-parent path.
    (root / "tiny.txt").write_text(
        "Short note about the structural slab pour.", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def smoke_corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("smoke_corpus")
    _build_synthetic_corpus(root)
    return root


# ----------------------------------------------------------------------
# Result bundle
# ----------------------------------------------------------------------


@dataclass
class SmokeResult:
    """Everything the end-to-end run produced."""

    corpus_root: Path
    processed: list[ProcessedDocument]
    all_chunks: list[ChunkRecord]
    classifier_results: dict[str, ClassifierResult]
    tree: OntologyTree
    pages: list[WikiPage]
    store: InMemoryPageStore


async def _run_pipeline(corpus_root: Path) -> SmokeResult:
    """Run the entire ingestion -> ontology -> pages loop once."""
    connector = LocalFolderConnector(
        corpus_root, tenant_id=SMOKE_TENANT_ID, source_id=SMOKE_SOURCE_ID
    )
    refs = list(connector.list())

    classifier = DocumentClassifier(
        StubLLMClassifier(), taxonomy=Taxonomy.starter()
    )
    parser_registry = ParserRegistry.default()
    embedding_provider = StubEmbeddingProvider()

    processed: list[ProcessedDocument] = []
    for ref in refs:
        # A fresh chunker per call so internal state never leaks across docs.
        chunker = Chunker(
            text_splitter=RecursiveCharacterSplitter(
                chunk_size=400, chunk_overlap=40
            )
        )
        out = await process_document(
            ref,
            connector=connector,
            parser_registry=parser_registry,
            chunker=chunker,
            embedding_provider=embedding_provider,
            classifier=classifier,
        )
        processed.append(out)

    # Aggregate all chunks across all documents.
    all_chunks: list[ChunkRecord] = []
    for pd in processed:
        all_chunks.extend(pd.chunks)

    # Build classifier_results keyed by document_content_hash - that is
    # what PageBuilder._doc_type_distribution looks up.
    classifier_results: dict[str, ClassifierResult] = {}
    for pd in processed:
        if pd.classification is None or not pd.chunks:
            continue
        # Every chunk in `pd.chunks` shares one document_content_hash.
        doc_hash = pd.chunks[0].document_content_hash
        classifier_results[doc_hash] = pd.classification

    # Induce the ontology.
    inducer = OntologyInducer()
    tree = await inducer.induce(all_chunks)

    # Build pages.
    store = InMemoryPageStore()
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=store,
    )
    pages = await pipeline.build_for_tree(
        tree, all_chunks, classifier_results, tenant_id=SMOKE_TENANT_ID
    )

    return SmokeResult(
        corpus_root=corpus_root,
        processed=processed,
        all_chunks=all_chunks,
        classifier_results=classifier_results,
        tree=tree,
        pages=pages,
        store=store,
    )


@pytest_asyncio.fixture(scope="module")
async def smoke_result(smoke_corpus_root: Path) -> SmokeResult:
    return await _run_pipeline(smoke_corpus_root)


@pytest.fixture(scope="module")
def run_pipeline_callable() -> Callable[[Path], "object"]:
    """Expose the runner so the determinism test can call it a second time.

    Returned object is the async coroutine factory; callers `await` it.
    """
    return _run_pipeline


__all__ = [
    "OTHER_TENANT_ID",
    "SMOKE_SOURCE_ID",
    "SMOKE_TENANT_ID",
    "SmokeResult",
    "run_pipeline_callable",
    "smoke_corpus_root",
    "smoke_result",
]

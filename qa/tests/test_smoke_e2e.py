"""M1-QA-01 — End-to-end smoke harness.

Exercises the full VersaWiki M1 pipeline from raw text files on disk
all the way through to queryable API pages, using stub / in-memory
implementations throughout.  No real LLM calls.  No network access.

Pipeline covered
----------------
LocalFolderConnector
    → parsers → Chunker → StubEmbeddingProvider
    → DocumentClassifier (StubLLMClassifier)
    → OntologyInducer (SimpleEmbeddingClusterer, StubTaxonomyProposer,
                        SimpleConnectedComponentsDetector)
    → PageBuildPipeline / StubPageWriter
    → InMemoryPageStore (ingestion)
    → [bridge: WikiPage → WikiPageRecord]
    → API InMemoryPageStore
    → GET /v1/tenants/{tid}/pages/{pid}      (REST)
    → MCP tools/call read_page               (JSON-RPC)

Why this lives in a separate qa/ package
-----------------------------------------
The api and ingestion services are intentionally independent pyproject.toml
packages that do not import each other at runtime.  The QA harness is the
only layer that legitimately needs to bridge them; pulling it into either
service would contaminate that service boundary.  See the PR body for the
full dependency-choice rationale.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ingestion imports
# ---------------------------------------------------------------------------
from versawiki_ingestion.chunking import Chunker, RecursiveCharacterSplitter
from versawiki_ingestion.classification import DocumentClassifier, StubLLMClassifier
from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
from versawiki_ingestion.embedding import StubEmbeddingProvider
from versawiki_ingestion.ontology import OntologyInducer
from versawiki_ingestion.pages import (
    InMemoryPageStore as IngestionPageStore,
    PageBuildPipeline,
    PageBuilder,
    StubPageWriter,
)
from versawiki_ingestion.pages.models import WikiPage
from versawiki_ingestion.parsers.registry import ParserRegistry
from versawiki_ingestion.pipeline import process_document

# ---------------------------------------------------------------------------
# API imports
# ---------------------------------------------------------------------------
from versawiki_api.app import create_app
from versawiki_api.auth.keys import InMemoryApiKeyStore, RedisCachedApiKeyStore
from versawiki_api.config import Settings, get_settings
from versawiki_api.db.tenant_store import InMemoryTenantStore
from versawiki_api.deps import set_page_store
from versawiki_api.pages_store import InMemoryPageStore as ApiPageStore
from versawiki_api.pages_store import WikiPageRecord


# ---------------------------------------------------------------------------
# Synthetic AEC corpus — 10 documents, mixed types.
#
# Each file repeats its content 8× so it produces enough chunks (~5-8
# per file) for the SimpleEmbeddingClusterer to form non-trivial clusters
# and for the PageBuildPipeline to materialise pages (≥2 chunks each).
# ---------------------------------------------------------------------------

_CORPUS_FILES: dict[str, str] = {
    # ---- Three RFIs ----
    "rfi_001.txt": (
        "RFI-001 submitted_by: Jane Doe (structural) assigned_to: mechanical team\n\n"
        "Question about HVAC duct routing through structural bay at grid line F-5. "
        "Current drawing shows conflict with W18x35 beam. "
        "Confirm if beam can be relocated or if alternative duct routing is required. "
        "Response needed before concrete pour scheduled for 2026-06-10. " * 8
    ),
    "rfi_002.txt": (
        "RFI-002 submitted_by: Bob Smith (civil) assigned_to: geotechnical engineer\n\n"
        "Clarification on compaction requirement for fill material below ground-floor "
        "slab in zone B. Specification 31 23 16 says 95% Proctor but the geotech "
        "report table 4-2 says 92%. Which governs? Contractor needs response "
        "prior to backfill activity. " * 8
    ),
    "rfi_003.txt": (
        "RFI-003 submitted_by: Carol Lee (MEP) assigned_to: architect "
        "response_pending\n\n"
        "Lighting fixture schedule on sheet E-401 lists type L-7 but reflected "
        "ceiling plan on A-601 shows L-9 in corridor 104. Please clarify correct "
        "fixture type. Lead time is 12 weeks; order must be placed by end of month "
        "to avoid schedule delay. " * 8
    ),
    # ---- Three specifications ----
    "spec_03300.txt": (
        "SECTION 03300 — CAST-IN-PLACE CONCRETE\n\n"
        "PART 1 GENERAL\n"
        "1.01 SCOPE: Formwork, reinforcement, mixing, placing, finishing and curing "
        "of cast-in-place concrete. Design strength: 4000 PSI at 28 days. "
        "Slump shall not exceed 4 inches at point of placement. "
        "Water-cement ratio max 0.45 for exposed concrete. " * 8
    ),
    "spec_09250.txt": (
        "SECTION 09250 — GYPSUM BOARD ASSEMBLIES\n\n"
        "PART 1 GENERAL\n"
        "1.01 SCOPE: Furnish and install gypsum board assemblies including metal "
        "framing, gypsum wallboard, shaft liner, abuse-resistant board and "
        "related accessories. Fire-rated assemblies shall be UL-listed. "
        "Minimum board thickness: 5/8 inch for fire-rated partitions. " * 8
    ),
    "spec_22000.txt": (
        "SECTION 22000 — PLUMBING GENERAL\n\n"
        "PART 1 GENERAL\n"
        "1.01 SCOPE: Domestic cold and hot water, sanitary drain, waste and vent "
        "systems, and storm drainage. All plumbing work shall conform to IPC 2021, "
        "state amendments, and local authority having jurisdiction requirements. "
        "Flow rate: lavatories 0.5 GPM, kitchen sinks 1.8 GPM. " * 8
    ),
    # ---- Two meeting-minutes ----
    "minutes_20260415.txt": (
        "MEETING MINUTES — Owner-Architect-Contractor (OAC) Meeting\n"
        "Date: April 15, 2026  Location: Site Trailer A\n\n"
        "Attendees: Josh (Owner), Maria (Architect), Sam (GC), Dave (MEP)\n"
        "1. Schedule: Foundation pour on track for April 28. "
        "2. RFI log reviewed; 3 open items over 7 days — escalate to PM. "
        "3. Submittal tracker: shop drawings for steel joist approved. "
        "4. Safety: no incidents this period. " * 8
    ),
    "minutes_20260429.txt": (
        "MEETING MINUTES — OAC Meeting\n"
        "Date: April 29, 2026  Location: Site Trailer A\n\n"
        "Attendees: Josh (Owner), Maria (Architect), Sam (GC)\n"
        "1. Foundation poured April 28 — passed inspection. "
        "2. Structural steel erection begins May 6. "
        "3. MEP coordination drawing review scheduled for May 3. "
        "4. Change order CO-04 approved for revised grading plan ($14,200). " * 8
    ),
    # ---- Two submittals ----
    "submittal_steel_joist.txt": (
        "SUBMITTAL — Structural Steel Joists\n"
        "Submittal No. S-031  Spec Section: 05 21 00\n"
        "Contractor: ABC Steel Inc.  Date: 2026-04-10\n\n"
        "Shop drawings for K-series open-web steel joists per design drawings "
        "S-201 through S-205. Joists conform to SJI K-series standard. "
        "Steel ASTM A36 / A572 Grade 50. Weld inspection per AWS D1.1. "
        "Engineer stamp attached. " * 8
    ),
    "submittal_fire_doors.txt": (
        "SUBMITTAL — Fire-Rated Door Assemblies\n"
        "Submittal No. S-047  Spec Section: 08 11 13\n"
        "Contractor: Premier Door and Frame  Date: 2026-04-22\n\n"
        "Product data and shop drawings for 90-minute rated hollow metal door "
        "frames and 90-minute fire doors for stairwell enclosures. "
        "Doors UL Label 10B. Frames per ANSI/NFPA 80. "
        "Coordinate with architect for hardware schedule. " * 8
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    """Run a coroutine to completion on a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _wiki_page_to_record(page: WikiPage) -> WikiPageRecord:
    """Bridge ingestion WikiPage → API WikiPageRecord.

    Both Pydantic v2 frozen models declare the same set of fields; the
    API model is explicitly documented as a mirror of the ingestion model.
    ``model_dump()`` produces a dict the WikiPageRecord constructor accepts
    unchanged.
    """
    return WikiPageRecord(**page.model_dump())


# ---------------------------------------------------------------------------
# Core async pipeline driver
# ---------------------------------------------------------------------------


async def _run_pipeline(
    corpus_root: Path,
    tenant_id: str,
) -> tuple[list, list]:
    """Run the full M1 ingestion pipeline over *corpus_root*.

    Returns ``(all_chunks, wiki_pages)``.
    """
    connector = LocalFolderConnector(
        corpus_root, tenant_id=tenant_id, source_id="s_smoke"
    )
    parser_registry = ParserRegistry.default()
    chunker = Chunker(
        text_splitter=RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=40)
    )
    embedding_provider = StubEmbeddingProvider()
    classifier = DocumentClassifier(StubLLMClassifier())

    all_chunks: list = []
    classifier_results: dict = {}

    for ref in connector.list():
        processed = await process_document(
            ref,
            connector=connector,
            parser_registry=parser_registry,
            chunker=chunker,
            embedding_provider=embedding_provider,
            classifier=classifier,
        )
        if processed:
            all_chunks.extend(processed.chunks)
            if processed.classification is not None:
                # Key by document_content_hash; all chunks from one document
                # share the same hash — the builder uses this map to derive
                # the predominant_doc_types field.
                for chunk in processed.chunks:
                    classifier_results[chunk.document_content_hash] = (
                        processed.classification
                    )

    # Induce the ontology tree (all defaults = stub/simple implementations).
    inducer = OntologyInducer()
    tree = await inducer.induce(all_chunks)

    # Build wiki pages.
    store = IngestionPageStore()
    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=StubPageWriter()),
        store=store,
    )
    pages = await pipeline.build_for_tree(
        tree, all_chunks, classifier_results, tenant_id=tenant_id
    )
    return all_chunks, pages


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# (module scope avoids re-running the ~100ms pipeline for every test)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _smoke_meta(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """One-shot setup: write corpus, run pipeline, create API infrastructure.

    Returns a dict with keys:
      api_key_store, tenant_store, tenant_id, raw_key, chunks, pages.
    """
    # 1. Write the synthetic corpus to a tmp directory.
    root = tmp_path_factory.mktemp("corpus")
    for name, content in _CORPUS_FILES.items():
        (root / name).write_text(content, encoding="utf-8")

    # 2. Create the tenant and issue an API key *before* the pipeline run
    #    so the pipeline uses the real tenant UUID as its tenant_id.
    api_key_store = RedisCachedApiKeyStore(InMemoryApiKeyStore())
    tenant_store = InMemoryTenantStore()
    tenant = _run(
        tenant_store.create(
            slug="smoke-test",
            display_name="Smoke Test Tenant",
            plan="free",
        )
    )
    _, raw_key = _run(
        api_key_store.issue(
            tenant_id=tenant.id,
            label="qa-smoke-key",
            scopes=("query",),
        )
    )

    # 3. Run the full pipeline with the tenant's UUID.
    all_chunks, wiki_pages = _run(_run_pipeline(root, tenant.id))

    return dict(
        api_key_store=api_key_store,
        tenant_store=tenant_store,
        tenant_id=tenant.id,
        raw_key=raw_key,
        chunks=all_chunks,
        pages=wiki_pages,
    )


@pytest.fixture(scope="module")
def _api_app(_smoke_meta: dict) -> FastAPI:
    """FastAPI app with smoke-pipeline pages pre-loaded into its page store."""
    # Bridge WikiPage objects from ingestion into the API's WikiPageRecord store.
    page_store = ApiPageStore()
    for page in _smoke_meta["pages"]:
        _run(page_store.upsert(_wiki_page_to_record(page)))

    get_settings.cache_clear()
    app = create_app(
        Settings(env="test", log_level="WARNING"),
        api_key_store=_smoke_meta["api_key_store"],
        tenant_store=_smoke_meta["tenant_store"],
    )
    set_page_store(app, page_store)
    return app


@pytest.fixture(scope="module")
def smoke_client(_api_app: FastAPI):
    """Synchronous TestClient for the entire smoke-test module."""
    with TestClient(_api_app) as client:
        yield client


@pytest.fixture(scope="module")
def smoke_headers(_smoke_meta: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_smoke_meta['raw_key']}"}


@pytest.fixture(scope="module")
def smoke_tenant_id(_smoke_meta: dict) -> str:
    return _smoke_meta["tenant_id"]


@pytest.fixture(scope="module")
def smoke_pages(_smoke_meta: dict) -> list:
    return _smoke_meta["pages"]


@pytest.fixture(scope="module")
def smoke_chunks(_smoke_meta: dict) -> list:
    return _smoke_meta["chunks"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineOutput:
    """Validate that the ingestion pipeline produces the expected artefacts."""

    def test_pipeline_produces_chunks_from_all_documents(self, smoke_chunks):
        """Every corpus document must contribute at least one chunk."""
        # 10 files × ~5-8 chunks each @ chunk_size=400 → ≥20 chunks.
        assert len(smoke_chunks) >= 20, (
            f"Expected ≥20 chunks from {len(_CORPUS_FILES)} corpus files; "
            f"got {len(smoke_chunks)}"
        )

    def test_pipeline_produces_at_least_one_page(self, smoke_pages):
        """The ontology inducer + page builder must materialise at least one page."""
        assert smoke_pages, "Pipeline produced no wiki pages"

    def test_all_pages_have_valid_required_fields(self, smoke_pages, smoke_tenant_id):
        """Every page carries non-empty title, summary, body, slug, and the
        correct tenant_id."""
        for page in smoke_pages:
            assert page.tenant_id == smoke_tenant_id, (
                f"Page {page.id} has tenant_id={page.tenant_id!r}; "
                f"expected {smoke_tenant_id!r}"
            )
            assert page.id, f"Page has empty id"
            assert page.title, f"Page {page.id} has empty title"
            assert page.summary, f"Page {page.id} has empty summary"
            assert page.body_markdown, f"Page {page.id} has empty body_markdown"
            assert page.slug, f"Page {page.id} has empty slug"
            assert page.chunk_ids, f"Page {page.id} has no chunk_ids"
            assert page.version >= 1

    def test_pages_have_non_duplicate_ids(self, smoke_pages):
        """Each page gets a stable unique id."""
        ids = [p.id for p in smoke_pages]
        assert len(ids) == len(set(ids)), "Duplicate page ids detected"

    def test_chunk_ids_reference_known_chunks(self, smoke_pages, smoke_chunks):
        """Page chunk_ids should all be found in the chunk set produced by the
        pipeline (every related chunk is traceable)."""
        known_hashes = {c.chunk_content_hash for c in smoke_chunks}
        for page in smoke_pages:
            for cid in page.chunk_ids:
                assert cid in known_hashes, (
                    f"Page {page.id} references unknown chunk {cid}"
                )


class TestRestApi:
    """Validate the GET /v1/tenants/{tid}/pages/{pid} REST route."""

    def test_known_page_returns_200_with_correct_fields(
        self,
        smoke_client,
        smoke_headers,
        smoke_pages,
        smoke_tenant_id,
    ):
        """The first pipeline-produced page is accessible via the REST API."""
        page = smoke_pages[0]
        response = smoke_client.get(
            f"/v1/tenants/{smoke_tenant_id}/pages/{page.id}",
            headers=smoke_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["page_id"] == page.id
        assert body["slug"] == page.slug
        assert body["title"] == page.title
        assert body["body_md"] == page.body_markdown
        assert body["primary_ontology_node_id"] == page.ontology_node_id
        assert body["is_stale"] is False

    def test_unknown_page_returns_structured_404(
        self,
        smoke_client,
        smoke_headers,
        smoke_tenant_id,
    ):
        """A non-existent page id returns a structured 404 error envelope."""
        response = smoke_client.get(
            f"/v1/tenants/{smoke_tenant_id}/pages/no-such-page",
            headers=smoke_headers,
        )
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "page_not_found"
        assert body["error"]["details"]["page_id"] == "no-such-page"

    def test_all_pipeline_pages_are_accessible_via_api(
        self,
        smoke_client,
        smoke_headers,
        smoke_pages,
        smoke_tenant_id,
    ):
        """Every page produced by the pipeline round-trips through the API."""
        for page in smoke_pages:
            response = smoke_client.get(
                f"/v1/tenants/{smoke_tenant_id}/pages/{page.id}",
                headers=smoke_headers,
            )
            assert response.status_code == 200, (
                f"Page {page.id} (slug={page.slug!r}) returned "
                f"{response.status_code}: {response.text}"
            )
            body = response.json()
            assert body["page_id"] == page.id

    def test_cross_tenant_access_returns_403(
        self,
        smoke_client,
        smoke_headers,
        smoke_pages,
    ):
        """Accessing a page under the wrong tenant_id is refused with 403."""
        page = smoke_pages[0]
        response = smoke_client.get(
            f"/v1/tenants/wrong-tenant-uuid/pages/{page.id}",
            headers=smoke_headers,
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "tenant_scope_mismatch"

    def test_unauthenticated_request_returns_401(
        self,
        smoke_client,
        smoke_pages,
        smoke_tenant_id,
    ):
        """A request without an Authorization header returns 401."""
        page = smoke_pages[0]
        response = smoke_client.get(
            f"/v1/tenants/{smoke_tenant_id}/pages/{page.id}",
        )
        assert response.status_code == 401


class TestMcpTool:
    """Validate the MCP tools/call read_page JSON-RPC route."""

    def test_mcp_read_page_returns_correct_page(
        self,
        smoke_client,
        smoke_headers,
        smoke_pages,
    ):
        """tools/call read_page returns the full wiki page produced by the
        pipeline, not a stub response."""
        page = smoke_pages[0]
        rpc = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "read_page",
                "arguments": {"page_id": page.id},
            },
        }
        response = smoke_client.post("/mcp", json=rpc, headers=smoke_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["jsonrpc"] == "2.0"
        assert "result" in payload, f"Expected result, got: {payload}"
        result = payload["result"]
        assert result["page_id"] == page.id
        assert result["title"] == page.title
        assert result["body_md"] == page.body_markdown
        assert result["primary_ontology_node_id"] == page.ontology_node_id

    def test_mcp_read_page_unknown_id_returns_not_found_envelope(
        self,
        smoke_client,
        smoke_headers,
    ):
        """Unknown page_id returns the JSON-RPC not_found error envelope,
        not an HTTP error."""
        rpc = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "read_page",
                "arguments": {"page_id": "definitely-does-not-exist"},
            },
        }
        response = smoke_client.post("/mcp", json=rpc, headers=smoke_headers)
        assert response.status_code == 200
        payload = response.json()
        assert "error" in payload
        assert payload["error"]["code"] == -32004  # not_found
        assert payload["error"]["data"]["page_id"] == "definitely-does-not-exist"

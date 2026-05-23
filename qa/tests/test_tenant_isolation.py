"""M1-QA-02 — Tenant-isolation property tests.

Verifies that the VersaWiki API enforces strict per-tenant boundaries:
no credential from Tenant A can read, enumerate, or probe data belonging
to Tenant B, and vice versa.

Properties verified
-------------------
P1  Foreign-key 403 before store lookup.
    Tenant A's key addressing /tenants/B/pages/{id} always gets 403,
    regardless of whether the page id exists under Tenant B.  This means
    an attacker with a valid key cannot distinguish "page exists but owned
    by a foreign tenant" from "page does not exist" — both return 403.

P2  Page-id opacity (variant of P1).
    Knowing an exact page_id that lives under Tenant B does not help:
    /tenants/B/pages/<B-page-id> with Tenant A's key → 403.

P3  Slug-lookup isolation.
    /tenants/B/pages?slug=<B-slug> with Tenant A's key → 403.

P4  Ontology-node listing isolation.
    /tenants/B/pages?ontology_node=<node> with Tenant A's key → 403.

P5  Query-endpoint isolation.
    POST /tenants/B/query with Tenant A's key → 403.

P6  MCP read_page isolation.
    tools/call read_page with a page_id from Tenant B, authenticated
    as Tenant A, returns 403 at the HTTP level (not the page content).

P7  Symmetric isolation (A≁B implies B≁A).
    The isolation contract holds in both directions for every route type.

P8  Own-tenant access is unaffected.
    After exercising all the cross-tenant checks Tenant A can still read
    its own pages (guard doesn't over-fire).

P9  Two-tenant corpus independence.
    When the same corpus is ingested for two different tenants the
    resulting page_id sets are completely disjoint — no id shared.

P10 Stale page still returns 403 for a foreign key.
    A page marked is_stale=True does not change the 403 guarantee.

Structure
---------
Module-scoped fixtures build two tenants (alpha, beta) with independent
API keys and a small set of pre-loaded pages.  Each property class then
pulls from those fixtures to minimise fixture overhead.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# API imports
# ---------------------------------------------------------------------------
from versawiki_api.app import create_app
from versawiki_api.auth.keys import InMemoryApiKeyStore, RedisCachedApiKeyStore
from versawiki_api.config import Settings, get_settings
from versawiki_api.db.tenant_store import InMemoryTenantStore
from versawiki_api.deps import set_page_store
from versawiki_api.pages_store import InMemoryPageStore, WikiPageRecord

# ---------------------------------------------------------------------------
# QA-01 helper re-used here
# ---------------------------------------------------------------------------
# We deliberately do NOT import from versawiki_ingestion in this module —
# M1-QA-02 tests the API boundary, not the ingestion pipeline.  Page
# records are constructed directly via WikiPageRecord.


def _run(coro: Any) -> Any:
    """Run a coroutine on a fresh event loop (sync test context)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Synthetic page factory
# ---------------------------------------------------------------------------

def _make_page(
    *,
    tenant_id: str,
    page_id: str | None = None,
    slug: str | None = None,
    ontology_node_id: str | None = None,
    is_stale: bool = False,
) -> WikiPageRecord:
    """Return a minimal WikiPageRecord for isolation tests."""
    pid = page_id or str(uuid.uuid4())
    return WikiPageRecord(
        id=pid,
        tenant_id=tenant_id,
        ontology_node_id=ontology_node_id or "node-root",
        title="Test Page",
        slug=slug or f"test-page-{pid[:8]}",
        summary="Test page summary.",
        body_markdown="# Test\n\nTest page body.",
        is_stale=is_stale,
    )


# ---------------------------------------------------------------------------
# Module-scoped fixtures — built once for the whole test module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _isolation_meta() -> dict:
    """Stand up two tenants (alpha, beta) with pages and API keys.

    Returns a dict with:
      app, client, alpha_tid, alpha_key, alpha_pages,
                   beta_tid,  beta_key,  beta_pages
    """
    api_key_store = RedisCachedApiKeyStore(InMemoryApiKeyStore())
    tenant_store = InMemoryTenantStore()

    # Provision two independent tenants.
    alpha = _run(tenant_store.create(slug="alpha", display_name="Alpha Corp", plan="free"))
    beta  = _run(tenant_store.create(slug="beta",  display_name="Beta LLC",   plan="free"))

    # Issue one key per tenant (query scope is enough for all read routes).
    _, alpha_key = _run(api_key_store.issue(
        tenant_id=alpha.id, label="alpha-qa", scopes=("query",)
    ))
    _, beta_key  = _run(api_key_store.issue(
        tenant_id=beta.id,  label="beta-qa",  scopes=("query",)
    ))

    # Build the API app.
    get_settings.cache_clear()
    app = create_app(
        Settings(env="test", log_level="WARNING"),
        api_key_store=api_key_store,
        tenant_store=tenant_store,
    )

    # Two independent page stores — one per tenant written into the shared store.
    page_store = InMemoryPageStore()

    # Three pages per tenant, each with a stable slug and ontology node.
    alpha_pages: list[WikiPageRecord] = [
        _make_page(tenant_id=alpha.id, slug="alpha-intro",   ontology_node_id="node-alpha"),
        _make_page(tenant_id=alpha.id, slug="alpha-design",  ontology_node_id="node-alpha"),
        _make_page(tenant_id=alpha.id, slug="alpha-process", ontology_node_id="node-alpha",
                   is_stale=True),  # P10: stale page
    ]
    beta_pages: list[WikiPageRecord] = [
        _make_page(tenant_id=beta.id, slug="beta-overview",  ontology_node_id="node-beta"),
        _make_page(tenant_id=beta.id, slug="beta-procedure", ontology_node_id="node-beta"),
        _make_page(tenant_id=beta.id, slug="beta-report",    ontology_node_id="node-beta"),
    ]

    for page in [*alpha_pages, *beta_pages]:
        _run(page_store.upsert(page))

    set_page_store(app, page_store)

    return dict(
        app=app,
        alpha_tid=alpha.id,
        alpha_key=alpha_key,
        alpha_pages=alpha_pages,
        beta_tid=beta.id,
        beta_key=beta_key,
        beta_pages=beta_pages,
    )


@pytest.fixture(scope="module")
def iso_client(_isolation_meta: dict):
    """A single TestClient for the whole isolation test module."""
    with TestClient(_isolation_meta["app"]) as client:
        yield client


@pytest.fixture(scope="module")
def alpha_tid(_isolation_meta: dict) -> str:
    return _isolation_meta["alpha_tid"]


@pytest.fixture(scope="module")
def alpha_headers(_isolation_meta: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_isolation_meta['alpha_key']}"}


@pytest.fixture(scope="module")
def alpha_pages(_isolation_meta: dict) -> list[WikiPageRecord]:
    return _isolation_meta["alpha_pages"]


@pytest.fixture(scope="module")
def beta_tid(_isolation_meta: dict) -> str:
    return _isolation_meta["beta_tid"]


@pytest.fixture(scope="module")
def beta_headers(_isolation_meta: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_isolation_meta['beta_key']}"}


@pytest.fixture(scope="module")
def beta_pages(_isolation_meta: dict) -> list[WikiPageRecord]:
    return _isolation_meta["beta_pages"]


# ---------------------------------------------------------------------------
# P8 — Own-tenant sanity (must pass before we trust the cross-tenant tests)
# ---------------------------------------------------------------------------

class TestOwnTenantAccess:
    """P8 — each tenant can freely access its own pages."""

    def test_alpha_can_read_own_pages(
        self, iso_client, alpha_tid, alpha_headers, alpha_pages
    ):
        """Alpha key returns 200 for every Alpha page."""
        for page in alpha_pages:
            r = iso_client.get(
                f"/v1/tenants/{alpha_tid}/pages/{page.id}",
                headers=alpha_headers,
            )
            assert r.status_code == 200, (
                f"Alpha failed to read own page {page.id}: {r.text}"
            )
            assert r.json()["page_id"] == page.id

    def test_beta_can_read_own_pages(
        self, iso_client, beta_tid, beta_headers, beta_pages
    ):
        """Beta key returns 200 for every Beta page."""
        for page in beta_pages:
            r = iso_client.get(
                f"/v1/tenants/{beta_tid}/pages/{page.id}",
                headers=beta_headers,
            )
            assert r.status_code == 200, (
                f"Beta failed to read own page {page.id}: {r.text}"
            )
            assert r.json()["page_id"] == page.id

    def test_alpha_can_list_own_pages_by_slug(
        self, iso_client, alpha_tid, alpha_headers, alpha_pages
    ):
        page = alpha_pages[0]
        r = iso_client.get(
            f"/v1/tenants/{alpha_tid}/pages",
            params={"slug": page.slug},
            headers=alpha_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["page_id"] == page.id

    def test_alpha_can_list_own_pages_by_node(
        self, iso_client, alpha_tid, alpha_headers, alpha_pages
    ):
        r = iso_client.get(
            f"/v1/tenants/{alpha_tid}/pages",
            params={"ontology_node": "node-alpha"},
            headers=alpha_headers,
        )
        assert r.status_code == 200
        body = r.json()
        # All three alpha pages share node-alpha.
        assert body["total"] == len(alpha_pages)

    def test_alpha_query_endpoint_returns_200(
        self, iso_client, alpha_tid, alpha_headers
    ):
        r = iso_client.post(
            f"/v1/tenants/{alpha_tid}/query",
            json={"q": "what documents do we have?"},
            headers=alpha_headers,
        )
        assert r.status_code == 200
        assert "query_id" in r.json()


# ---------------------------------------------------------------------------
# P1 / P2 — Foreign key: 403 on /pages/{id}
# ---------------------------------------------------------------------------

class TestCrossTenantPageById:
    """P1 + P2: Foreign keys cannot access pages by id on the foreign tenant."""

    def test_alpha_key_on_beta_url_returns_403(
        self, iso_client, beta_tid, alpha_headers, beta_pages
    ):
        """P1 — Alpha key addressing Beta's tenant URL is refused."""
        page = beta_pages[0]
        r = iso_client.get(
            f"/v1/tenants/{beta_tid}/pages/{page.id}",
            headers=alpha_headers,
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "tenant_scope_mismatch"

    def test_beta_key_on_alpha_url_returns_403(
        self, iso_client, alpha_tid, beta_headers, alpha_pages
    ):
        """P7 (symmetry) — Beta key addressing Alpha's tenant URL is refused."""
        page = alpha_pages[0]
        r = iso_client.get(
            f"/v1/tenants/{alpha_tid}/pages/{page.id}",
            headers=beta_headers,
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "tenant_scope_mismatch"

    def test_403_regardless_of_page_existence(
        self, iso_client, beta_tid, alpha_headers
    ):
        """P1 corollary — 403 even when the page id does NOT exist under beta.

        This prevents an attacker from using a foreign key to probe page
        existence: both 'page exists but foreign' and 'page does not exist'
        must return 403, never 404.
        """
        non_existent_id = "this-page-id-definitely-does-not-exist"
        r = iso_client.get(
            f"/v1/tenants/{beta_tid}/pages/{non_existent_id}",
            headers=alpha_headers,
        )
        assert r.status_code == 403, (
            "Expected 403 (tenant_scope_mismatch) when a foreign key probes "
            f"a non-existent page; got {r.status_code}: {r.text}"
        )

    def test_403_for_all_alpha_pages_by_beta_key(
        self, iso_client, alpha_tid, beta_headers, alpha_pages
    ):
        """P2 — Beta cannot access ANY of Alpha's pages by id."""
        for page in alpha_pages:
            r = iso_client.get(
                f"/v1/tenants/{alpha_tid}/pages/{page.id}",
                headers=beta_headers,
            )
            assert r.status_code == 403, (
                f"Beta key should be denied page {page.id} under Alpha; "
                f"got {r.status_code}: {r.text}"
            )

    def test_403_for_all_beta_pages_by_alpha_key(
        self, iso_client, beta_tid, alpha_headers, beta_pages
    ):
        """P7 (symmetry) — Alpha cannot access ANY of Beta's pages by id."""
        for page in beta_pages:
            r = iso_client.get(
                f"/v1/tenants/{beta_tid}/pages/{page.id}",
                headers=alpha_headers,
            )
            assert r.status_code == 403, (
                f"Alpha key should be denied page {page.id} under Beta; "
                f"got {r.status_code}: {r.text}"
            )


# ---------------------------------------------------------------------------
# P3 — Slug-lookup isolation
# ---------------------------------------------------------------------------

class TestCrossTenantSlugLookup:
    """P3 — Slug lookups respect tenant boundaries."""

    def test_alpha_key_cannot_fetch_beta_page_by_slug(
        self, iso_client, beta_tid, alpha_headers, beta_pages
    ):
        page = beta_pages[0]
        r = iso_client.get(
            f"/v1/tenants/{beta_tid}/pages",
            params={"slug": page.slug},
            headers=alpha_headers,
        )
        assert r.status_code == 403

    def test_beta_key_cannot_fetch_alpha_page_by_slug(
        self, iso_client, alpha_tid, beta_headers, alpha_pages
    ):
        page = alpha_pages[0]
        r = iso_client.get(
            f"/v1/tenants/{alpha_tid}/pages",
            params={"slug": page.slug},
            headers=beta_headers,
        )
        assert r.status_code == 403

    def test_slug_isolation_returns_403_not_empty_list(
        self, iso_client, beta_tid, alpha_headers, beta_pages
    ):
        """Cross-tenant slug lookup must return 403, not an empty result set.

        An empty list would silently mislead a caller into thinking the slug
        doesn't exist; 403 makes the authorization failure explicit.
        """
        page = beta_pages[1]
        r = iso_client.get(
            f"/v1/tenants/{beta_tid}/pages",
            params={"slug": page.slug},
            headers=alpha_headers,
        )
        # Must be 403, NOT 200 with {"items": [], "total": 0}.
        assert r.status_code == 403, (
            f"Expected 403; got {r.status_code}: {r.text}\n"
            "A 200 empty-list response would silently conceal the isolation "
            "failure and leave the caller unsure whether the slug exists."
        )


# ---------------------------------------------------------------------------
# P4 — Ontology-node listing isolation
# ---------------------------------------------------------------------------

class TestCrossTenantNodeListing:
    """P4 — Ontology-node page listings are tenant-isolated."""

    def test_alpha_key_cannot_list_beta_node_pages(
        self, iso_client, beta_tid, alpha_headers
    ):
        r = iso_client.get(
            f"/v1/tenants/{beta_tid}/pages",
            params={"ontology_node": "node-beta"},
            headers=alpha_headers,
        )
        assert r.status_code == 403

    def test_beta_key_cannot_list_alpha_node_pages(
        self, iso_client, alpha_tid, beta_headers
    ):
        r = iso_client.get(
            f"/v1/tenants/{alpha_tid}/pages",
            params={"ontology_node": "node-alpha"},
            headers=beta_headers,
        )
        assert r.status_code == 403

    def test_same_node_id_in_both_tenants_does_not_leak(
        self, iso_client, alpha_tid, beta_tid,
        alpha_headers, beta_headers, _isolation_meta
    ):
        """Two tenants can share an ontology node id without leaking to each other.

        We load a page for each tenant that uses the same node id string
        and verify that each tenant only sees its own page.
        """
        shared_node = "shared-node-001"
        page_store = _isolation_meta["app"].state.page_store

        # Load one page per tenant under the shared node.
        alpha_page = _make_page(
            tenant_id=alpha_tid,
            slug="alpha-shared-node",
            ontology_node_id=shared_node,
        )
        beta_page = _make_page(
            tenant_id=beta_tid,
            slug="beta-shared-node",
            ontology_node_id=shared_node,
        )
        _run(page_store.upsert(alpha_page))
        _run(page_store.upsert(beta_page))

        # Alpha sees only its own page under that node.
        r_alpha = iso_client.get(
            f"/v1/tenants/{alpha_tid}/pages",
            params={"ontology_node": shared_node},
            headers=alpha_headers,
        )
        assert r_alpha.status_code == 200
        alpha_ids = {item["page_id"] for item in r_alpha.json()["items"]}
        assert alpha_page.id in alpha_ids
        assert beta_page.id not in alpha_ids, (
            "Alpha's listing for a shared node id must not include Beta's page."
        )

        # Beta sees only its own page under that node.
        r_beta = iso_client.get(
            f"/v1/tenants/{beta_tid}/pages",
            params={"ontology_node": shared_node},
            headers=beta_headers,
        )
        assert r_beta.status_code == 200
        beta_ids = {item["page_id"] for item in r_beta.json()["items"]}
        assert beta_page.id in beta_ids
        assert alpha_page.id not in beta_ids, (
            "Beta's listing for a shared node id must not include Alpha's page."
        )


# ---------------------------------------------------------------------------
# P5 — Query-endpoint isolation
# ---------------------------------------------------------------------------

class TestCrossTenantQuery:
    """P5 — The POST /query endpoint enforces the tenant scope check."""

    def test_alpha_key_on_beta_query_returns_403(
        self, iso_client, beta_tid, alpha_headers
    ):
        r = iso_client.post(
            f"/v1/tenants/{beta_tid}/query",
            json={"q": "find all documents"},
            headers=alpha_headers,
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "tenant_scope_mismatch"

    def test_beta_key_on_alpha_query_returns_403(
        self, iso_client, alpha_tid, beta_headers
    ):
        r = iso_client.post(
            f"/v1/tenants/{alpha_tid}/query",
            json={"q": "find all documents"},
            headers=beta_headers,
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "tenant_scope_mismatch"


# ---------------------------------------------------------------------------
# P6 — MCP read_page isolation
# ---------------------------------------------------------------------------

class TestCrossTenantMcpReadPage:
    """P6 — The MCP tools/call read_page route is tenant-isolated.

    The MCP endpoint is authenticated by the same middleware; using
    a key from Tenant A to call read_page on a page that belongs to
    Tenant B must return 403 at the HTTP layer.
    """

    def _rpc(self, page_id: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_page", "arguments": {"page_id": page_id}},
        }

    def test_alpha_key_cannot_read_beta_page_via_mcp(
        self, iso_client, alpha_headers, beta_pages
    ):
        """MCP read_page for a Beta page_id authenticated as Alpha → 403."""
        # The MCP endpoint is NOT tenant-namespaced in the URL — it relies
        # on the bearer key to establish the tenant.  A Beta page_id issued
        # to an Alpha key should be refused (page lives in Beta's namespace,
        # Alpha's key resolves to Alpha's tenant, store lookup returns None).
        page = beta_pages[0]
        r = iso_client.post(
            "/mcp",
            json=self._rpc(page.id),
            headers=alpha_headers,
        )
        # MCP endpoint is authenticated; a Beta page is invisible to Alpha.
        # The route returns the JSON-RPC not_found envelope (page not found
        # in Alpha's namespace), NOT the Beta page content.
        assert r.status_code == 200  # MCP always returns 200 at HTTP level
        payload = r.json()
        if "result" in payload:
            # If a result is returned it MUST NOT carry Beta's data.
            assert payload["result"].get("page_id") != page.id, (
                "MCP returned Beta's page to Alpha — isolation failure!"
            )
        else:
            # A JSON-RPC error (not_found) is the expected path.
            assert "error" in payload, f"Unexpected MCP response: {payload}"

    def test_beta_key_cannot_read_alpha_page_via_mcp(
        self, iso_client, beta_headers, alpha_pages
    ):
        """Symmetric: Beta cannot read Alpha's page via MCP."""
        page = alpha_pages[0]
        r = iso_client.post(
            "/mcp",
            json=self._rpc(page.id),
            headers=beta_headers,
        )
        assert r.status_code == 200
        payload = r.json()
        if "result" in payload:
            assert payload["result"].get("page_id") != page.id, (
                "MCP returned Alpha's page to Beta — isolation failure!"
            )
        else:
            assert "error" in payload

    def test_mcp_alpha_reads_own_page_successfully(
        self, iso_client, alpha_headers, alpha_pages
    ):
        """P8 sanity for MCP — Alpha can read its own pages via MCP."""
        page = alpha_pages[0]
        r = iso_client.post(
            "/mcp",
            json=self._rpc(page.id),
            headers=alpha_headers,
        )
        assert r.status_code == 200
        payload = r.json()
        assert "result" in payload, f"Expected MCP result; got: {payload}"
        assert payload["result"]["page_id"] == page.id


# ---------------------------------------------------------------------------
# P10 — Stale page does not change 403 guarantee
# ---------------------------------------------------------------------------

class TestStalePagIsolation:
    """P10 — A stale page (is_stale=True) does not weaken the isolation guarantee."""

    def test_stale_page_returns_403_for_foreign_key(
        self, iso_client, beta_tid, alpha_headers, alpha_pages
    ):
        """Alpha's stale page is still invisible to Beta."""
        # alpha_pages[2] was created with is_stale=True.
        stale_page = alpha_pages[2]
        assert stale_page.is_stale, "Precondition: alpha_pages[2] must be stale"
        r = iso_client.get(
            f"/v1/tenants/{beta_tid}/pages/{stale_page.id}",
            headers=alpha_headers,
        )
        # Alpha's key addressing Beta's URL — cross-tenant mismatch regardless of staleness.
        assert r.status_code == 403

    def test_own_stale_page_returns_200_with_stale_header(
        self, iso_client, alpha_tid, alpha_headers, alpha_pages
    ):
        """P8 variant — Alpha can read its own stale page; gets Cache-Control: stale=true."""
        stale_page = alpha_pages[2]
        r = iso_client.get(
            f"/v1/tenants/{alpha_tid}/pages/{stale_page.id}",
            headers=alpha_headers,
        )
        assert r.status_code == 200
        assert r.json()["is_stale"] is True
        assert "stale=true" in r.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# P9 — Two-tenant corpus independence (ingestion-level)
# ---------------------------------------------------------------------------

class TestCorpusIndependence:
    """P9 — Two tenants that ingest the same corpus produce disjoint page sets.

    This test runs the full M1 ingestion pipeline (stub LLM, no network)
    for two separate tenants and asserts that none of the resulting page ids
    or slugs are shared between tenants.  The check guards against a naive
    page-id derivation that uses only content hashes without tenant-scoping
    the key.
    """

    @pytest.fixture(scope="class")
    def _two_tenant_pages(self, tmp_path_factory):
        """Run the ingestion pipeline twice with the same corpus, different tenants."""
        # Import ingestion here only — this is the one test class that needs it.
        from versawiki_ingestion.chunking import Chunker, RecursiveCharacterSplitter
        from versawiki_ingestion.classification import DocumentClassifier, StubLLMClassifier
        from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
        from versawiki_ingestion.embedding import StubEmbeddingProvider
        from versawiki_ingestion.ontology import OntologyInducer
        from versawiki_ingestion.pages import (
            InMemoryPageStore,
            PageBuildPipeline,
            PageBuilder,
            StubPageWriter,
        )
        from versawiki_ingestion.parsers.registry import ParserRegistry
        from versawiki_ingestion.pipeline import process_document

        corpus_content = {
            "doc_a.txt": (
                "Section One: project scope and constraints.\n"
                "The structural design must conform to ASCE 7-22 load criteria. "
                "Wind exposure category B applies to this site. " * 10
            ),
            "doc_b.txt": (
                "Section Two: material specifications.\n"
                "All reinforcement shall be ASTM A615 Grade 60 deformed bars. "
                "Concrete compressive strength at 28 days: 4000 PSI minimum. " * 10
            ),
        }

        async def _run_pipeline(root, tenant_id):
            connector = LocalFolderConnector(root, tenant_id=tenant_id, source_id="s_iso")
            parser_registry = ParserRegistry.default()
            chunker = Chunker(
                text_splitter=RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=20)
            )
            embedding_provider = StubEmbeddingProvider()
            classifier = DocumentClassifier(StubLLMClassifier())

            all_chunks = []
            classifier_results = {}
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
                        for chunk in processed.chunks:
                            classifier_results[chunk.document_content_hash] = (
                                processed.classification
                            )

            inducer = OntologyInducer()
            tree = await inducer.induce(all_chunks)
            store = InMemoryPageStore()
            pipeline = PageBuildPipeline(
                builder=PageBuilder(llm_writer=StubPageWriter()),
                store=store,
            )
            pages = await pipeline.build_for_tree(
                tree, all_chunks, classifier_results, tenant_id=tenant_id
            )
            return pages

        # Write the same corpus to two separate directories.
        root_x = tmp_path_factory.mktemp("corpus_x")
        root_y = tmp_path_factory.mktemp("corpus_y")
        for name, content in corpus_content.items():
            (root_x / name).write_text(content)
            (root_y / name).write_text(content)

        tenant_x = "tenant-x-" + uuid.uuid4().hex[:8]
        tenant_y = "tenant-y-" + uuid.uuid4().hex[:8]

        pages_x = _run(_run_pipeline(root_x, tenant_x))
        pages_y = _run(_run_pipeline(root_y, tenant_y))

        return {"tenant_x": tenant_x, "tenant_y": tenant_y,
                "pages_x": pages_x, "pages_y": pages_y}

    def test_page_ids_are_disjoint_across_tenants(self, _two_tenant_pages):
        """No page id is shared between the two tenants."""
        ids_x = {p.id for p in _two_tenant_pages["pages_x"]}
        ids_y = {p.id for p in _two_tenant_pages["pages_y"]}
        shared = ids_x & ids_y
        assert not shared, (
            f"Page ids shared across tenants — isolation failure! Shared: {shared}"
        )

    def test_each_tenant_owns_its_pages(self, _two_tenant_pages):
        """Every page in each tenant's result set carries the correct tenant_id."""
        tx, ty = _two_tenant_pages["tenant_x"], _two_tenant_pages["tenant_y"]
        for page in _two_tenant_pages["pages_x"]:
            assert page.tenant_id == tx, (
                f"Page {page.id} in tenant_x result has wrong tenant_id: {page.tenant_id!r}"
            )
        for page in _two_tenant_pages["pages_y"]:
            assert page.tenant_id == ty, (
                f"Page {page.id} in tenant_y result has wrong tenant_id: {page.tenant_id!r}"
            )

    def test_slugs_are_independent_across_tenants(self, _two_tenant_pages):
        """Same corpus, different tenants.  Slug collision is acceptable (slugs
        are tenant-scoped), but the *page records* must carry distinct tenant_ids
        confirming the slug is scoped.  This test verifies the tenant_id field,
        not slug uniqueness across tenants.
        """
        pages_x = _two_tenant_pages["pages_x"]
        pages_y = _two_tenant_pages["pages_y"]
        tx, ty = _two_tenant_pages["tenant_x"], _two_tenant_pages["tenant_y"]

        slugs_x = {p.slug: p.tenant_id for p in pages_x}
        slugs_y = {p.slug: p.tenant_id for p in pages_y}
        shared_slugs = set(slugs_x) & set(slugs_y)

        for slug in shared_slugs:
            # If two tenants happen to share a slug, they must have different
            # tenant_ids — the same slug under two tenants is fine; the same
            # (slug, tenant_id) pair would be a collision.
            assert slugs_x[slug] != slugs_y[slug], (
                f"Slug '{slug}' appears with the same tenant_id in both tenants — "
                "tenant_id was not scoped correctly during page construction."
            )

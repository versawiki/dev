"""Fixtures for the demo viewer tests.

We never run real ingestion in tests — these fixtures seed the api's
``InMemoryPageStore`` with 3 hand-built :class:`WikiPageRecord`
instances, mount the viewer router on a fresh api app, and hand a
:class:`fastapi.testclient.TestClient` back to the test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from versawiki_api.app import create_app
from versawiki_api.deps import set_page_store
from versawiki_api.pages_store import InMemoryPageStore, WikiPageRecord

from versawiki_demo import viewer


DEMO_TENANT_ID = "demo-tenant"


def _make_seed_records() -> list[WikiPageRecord]:
    """Three synthetic records: two RFIs, one meeting-minutes.

    Includes one cross-link (rfi-001 -> minutes-001) so the related
    pages sidebar has something to render.
    """
    now = datetime(2026, 5, 26, tzinfo=timezone.utc)
    return [
        WikiPageRecord(
            id="rfi-001",
            tenant_id=DEMO_TENANT_ID,
            ontology_node_id="node-rfi",
            title="Concrete Mix RFI",
            slug="concrete-mix-rfi",
            summary="An RFI about concrete mix design clarifications submitted by Jane Doe.",
            body_markdown=(
                "## Overview\n\n"
                "This page summarises **RFI 042** regarding concrete mix.\n\n"
                "### Key questions\n\n"
                "- Should mix design account for cold weather?\n"
                "- Who reviews the response?\n"
            ),
            chunk_ids=["chunk-1", "chunk-2"],
            related_page_ids=["minutes-001"],
            created_at=now,
            updated_at=now,
            is_stale=False,
            version=1,
            source_uri_count=1,
            predominant_doc_types=["rfi"],
        ),
        WikiPageRecord(
            id="rfi-002",
            tenant_id=DEMO_TENANT_ID,
            ontology_node_id="node-rfi",
            title="Rebar Spacing RFI",
            slug="rebar-spacing-rfi",
            summary="Question about rebar spacing in the slab on grade. Filed by Bob.",
            body_markdown=(
                "## Overview\n\n"
                "RFI 057 covers rebar spacing concerns.\n\n"
                "### Resolution\n\n"
                "Awaiting structural engineer response.\n"
            ),
            chunk_ids=["chunk-3"],
            related_page_ids=[],
            created_at=now,
            updated_at=now,
            is_stale=False,
            version=1,
            source_uri_count=1,
            predominant_doc_types=["rfi"],
        ),
        WikiPageRecord(
            id="minutes-001",
            tenant_id=DEMO_TENANT_ID,
            ontology_node_id="node-minutes",
            title="Weekly Coordination Meeting",
            slug="weekly-coordination-meeting",
            summary="Notes from the weekly OAC meeting covering schedule and open items.",
            body_markdown=(
                "## Attendees\n\n"
                "Alice, Bob, Carol, Dave\n\n"
                "### Action items\n\n"
                "1. Review structural drawings\n"
                "2. Respond to all open RFIs\n"
            ),
            chunk_ids=["chunk-4", "chunk-5"],
            related_page_ids=[],
            created_at=now,
            updated_at=now,
            is_stale=False,
            version=1,
            source_uri_count=1,
            predominant_doc_types=["meeting_minutes"],
        ),
    ]


@pytest.fixture
def seed_records() -> list[WikiPageRecord]:
    return _make_seed_records()


@pytest.fixture
def viewer_app(seed_records):
    """A fully-wired FastAPI app with the viewer mounted + pages seeded.

    Returns the app instance; tests typically wrap it in a TestClient
    via the ``client`` fixture below.
    """
    import asyncio

    fastapi_app = create_app()
    store = InMemoryPageStore()

    async def _populate():
        for rec in seed_records:
            await store.upsert(rec)

    asyncio.run(_populate())

    set_page_store(fastapi_app, store)
    fastapi_app.state.demo_tenant_id = DEMO_TENANT_ID
    # Mirror the cli's helper-cache attribute so the viewer's homepage
    # iteration is fast/predictable in tests.
    store._demo_cached_pages = list(seed_records)  # type: ignore[attr-defined]
    fastapi_app.include_router(viewer.router)
    return fastapi_app


@pytest.fixture
def client(viewer_app):
    return TestClient(viewer_app)

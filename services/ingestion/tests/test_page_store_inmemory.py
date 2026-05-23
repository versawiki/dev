"""Tests for `InMemoryPageStore`."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from versawiki_ingestion.pages import InMemoryPageStore, WikiPage


def _page(
    page_id: str,
    *,
    tenant_id: str = "t1",
    ontology_node_id: str = "topic_a",
    slug: str = "topic-a",
) -> WikiPage:
    return WikiPage(
        id=page_id,
        tenant_id=tenant_id,
        ontology_node_id=ontology_node_id,
        title=f"Title {page_id}",
        slug=slug,
        summary="summary",
        body_markdown="## Overview\n",
        chunk_ids=[],
        related_page_ids=[],
        created_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        is_stale=False,
        version=1,
        source_uri_count=0,
        predominant_doc_types=[],
    )


@pytest.mark.asyncio
async def test_upsert_then_get_roundtrip():
    store = InMemoryPageStore()
    page = _page("pg1")
    await store.upsert(page)
    out = await store.get("t1", "pg1")
    assert out is not None
    assert out.id == "pg1"


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown():
    store = InMemoryPageStore()
    assert await store.get("t1", "missing") is None


@pytest.mark.asyncio
async def test_get_by_slug():
    store = InMemoryPageStore()
    await store.upsert(_page("pg1", slug="topic-alpha"))
    await store.upsert(_page("pg2", slug="topic-beta"))
    found = await store.get_by_slug("t1", "topic-alpha")
    assert found is not None
    assert found.id == "pg1"
    assert await store.get_by_slug("t1", "non-existent") is None


@pytest.mark.asyncio
async def test_get_by_slug_is_tenant_scoped():
    store = InMemoryPageStore()
    await store.upsert(_page("pg1", tenant_id="t1", slug="dup-slug"))
    await store.upsert(_page("pg2", tenant_id="t2", slug="dup-slug"))
    # Querying tenant t1 should not return t2's page even with same slug.
    found = await store.get_by_slug("t1", "dup-slug")
    assert found is not None
    assert found.tenant_id == "t1"
    assert found.id == "pg1"


@pytest.mark.asyncio
async def test_list_for_node():
    store = InMemoryPageStore()
    await store.upsert(_page("pg1", ontology_node_id="topic_x"))
    await store.upsert(_page("pg2", ontology_node_id="topic_x"))
    await store.upsert(_page("pg3", ontology_node_id="topic_y"))
    out = await store.list_for_node("t1", "topic_x")
    assert {p.id for p in out} == {"pg1", "pg2"}
    other = await store.list_for_node("t1", "topic_y")
    assert {p.id for p in other} == {"pg3"}


@pytest.mark.asyncio
async def test_list_for_node_tenant_scoped():
    store = InMemoryPageStore()
    await store.upsert(_page("pg1", tenant_id="t1", ontology_node_id="topic_a"))
    await store.upsert(_page("pg2", tenant_id="t2", ontology_node_id="topic_a"))
    out = await store.list_for_node("t1", "topic_a")
    assert {p.id for p in out} == {"pg1"}


@pytest.mark.asyncio
async def test_mark_stale():
    store = InMemoryPageStore()
    await store.upsert(_page("pg1"))
    updated = await store.mark_stale("t1", "pg1")
    assert updated is not None
    assert updated.is_stale is True
    # Roundtrip still says stale.
    out = await store.get("t1", "pg1")
    assert out is not None
    assert out.is_stale is True


@pytest.mark.asyncio
async def test_mark_stale_returns_none_for_unknown():
    store = InMemoryPageStore()
    out = await store.mark_stale("t1", "missing")
    assert out is None


@pytest.mark.asyncio
async def test_concurrent_upserts_dont_corrupt():
    store = InMemoryPageStore()
    pages = [_page(f"pg{i}") for i in range(50)]

    await asyncio.gather(*(store.upsert(p) for p in pages))

    # Every page should be retrievable.
    for p in pages:
        out = await store.get("t1", p.id)
        assert out is not None
        assert out.id == p.id


@pytest.mark.asyncio
async def test_upsert_overwrites_existing():
    store = InMemoryPageStore()
    p1 = _page("pg1")
    await store.upsert(p1)
    # Bump version via the page's own helper, then re-upsert.
    p2 = p1.bump_version(summary="new summary")
    await store.upsert(p2)
    out = await store.get("t1", "pg1")
    assert out is not None
    assert out.summary == "new summary"
    assert out.version == 2

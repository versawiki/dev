"""Staleness hook tests: ingestion events flip pages stale."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from versawiki_ingestion.pages import (
    StalenessEvent,
    WikiPage,
    mark_stale_on_event,
)


def _page(
    page_id: str = "pg_abc",
    *,
    tenant_id: str = "t1",
    ontology_node_id: str = "topic_a",
    is_stale: bool = False,
) -> WikiPage:
    return WikiPage(
        id=page_id,
        tenant_id=tenant_id,
        ontology_node_id=ontology_node_id,
        title="Topic A",
        slug="topic-a",
        summary="...",
        body_markdown="## Overview\n",
        chunk_ids=[],
        related_page_ids=[],
        created_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
        is_stale=is_stale,
        version=1,
        source_uri_count=0,
        predominant_doc_types=[],
    )


def test_chunk_added_event_marks_matching_node_stale():
    page = _page(ontology_node_id="topic_a")
    event = StalenessEvent.for_chunk_added(
        tenant_id="t1", ontology_node_ids=["topic_a"]
    )
    out = mark_stale_on_event(page, event)
    assert out.is_stale is True


def test_chunk_added_event_does_not_touch_other_nodes():
    page = _page(ontology_node_id="topic_b")
    event = StalenessEvent.for_chunk_added(
        tenant_id="t1", ontology_node_ids=["topic_a"]
    )
    out = mark_stale_on_event(page, event)
    assert out.is_stale is False


def test_chunk_deleted_event_marks_matching_node_stale():
    page = _page(ontology_node_id="topic_x")
    event = StalenessEvent.for_chunk_deleted(
        tenant_id="t1", ontology_node_ids=["topic_x", "topic_y"]
    )
    out = mark_stale_on_event(page, event)
    assert out.is_stale is True


def test_ontology_re_induced_marks_every_page_stale():
    page_a = _page("pg_a", ontology_node_id="topic_a")
    page_b = _page("pg_b", ontology_node_id="topic_b")
    event = StalenessEvent.for_ontology_re_induced(tenant_id="t1")
    out_a = mark_stale_on_event(page_a, event)
    out_b = mark_stale_on_event(page_b, event)
    assert out_a.is_stale is True
    assert out_b.is_stale is True


def test_cross_tenant_event_ignored():
    page = _page(tenant_id="t1", ontology_node_id="topic_a")
    event = StalenessEvent.for_chunk_added(
        tenant_id="t2", ontology_node_ids=["topic_a"]
    )
    out = mark_stale_on_event(page, event)
    assert out.is_stale is False


def test_already_stale_page_stays_stale_and_is_idempotent():
    page = _page(is_stale=True)
    event = StalenessEvent.for_chunk_added(
        tenant_id="t1", ontology_node_ids=["topic_a"]
    )
    out = mark_stale_on_event(page, event)
    assert out.is_stale is True
    # Same object identity is fine (we returned early).
    assert out is page


def test_event_factories_compose_correctly():
    a = StalenessEvent.for_chunk_added(
        tenant_id="t1", ontology_node_ids=["n1", "n2"]
    )
    assert a.kind == "chunk_added"
    assert a.ontology_node_ids == ("n1", "n2")
    assert a.affects_all is False

    b = StalenessEvent.for_ontology_re_induced(tenant_id="t1")
    assert b.kind == "ontology_re_induced"
    assert b.affects_all is True

"""Property-style tenant-isolation tests for ``InMemoryPageStore`` (M1-QA-02).

These tests complement the small example-based tests in
``tests/test_page_store_inmemory.py`` by driving the store with many
randomly-generated tenant configurations (seeded `random.Random` so
runs are deterministic). The goal is to push tenant-isolation hard:
hundreds of cross-tenant probes per test, intentional id/slug/node
collisions across tenants, and a concurrent-upsert fan-out.

We do NOT use ``hypothesis`` — it isn't a project dep — so we roll a
small seeded-random generator inline.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from versawiki_ingestion.pages import InMemoryPageStore, WikiPage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Fixed seed so the property tests are deterministic across CI runs.
SEED = 20260524


def _page(
    page_id: str,
    *,
    tenant_id: str = "t1",
    ontology_node_id: str = "topic_a",
    slug: str = "topic-a",
    created_at: datetime | None = None,
) -> WikiPage:
    """Mirror of the helper in ``tests/test_page_store_inmemory.py``.

    Kept local so this test file is self-contained.
    """
    ts = created_at or datetime(2026, 5, 23, tzinfo=timezone.utc)
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
        created_at=ts,
        updated_at=ts,
        is_stale=False,
        version=1,
        source_uri_count=0,
        predominant_doc_types=[],
    )


def _rand_tenant_id(rng: random.Random, idx: int) -> str:
    """Mix UUID-shaped and slug-shaped tenant ids."""
    if rng.random() < 0.5:
        # UUID-shaped (derived from RNG so it's reproducible).
        return str(uuid.UUID(int=rng.getrandbits(128)))
    # Slug-shaped.
    return f"tenant-{idx:03d}-{rng.choice(['acme', 'globex', 'initech', 'umbrella', 'wonka'])}"


def _build_random_dataset(
    rng: random.Random,
    *,
    num_tenants: int = 20,
    min_pages: int = 1,
    max_pages: int = 5,
    shared_id_pool_size: int = 8,
    shared_slug_pool_size: int = 6,
    shared_node_pool_size: int = 6,
) -> tuple[list[str], list[WikiPage]]:
    """Build a (tenant_ids, pages) pair with intentional cross-tenant collisions.

    Some page ids, slugs, and node ids are drawn from small shared pools
    so the same string shows up under multiple tenants. The store must
    keep them isolated.
    """
    tenants = [_rand_tenant_id(rng, i) for i in range(num_tenants)]
    # Pools of values that several tenants may pull from.
    shared_ids = [f"pg-shared-{i:02d}" for i in range(shared_id_pool_size)]
    shared_slugs = [f"shared-slug-{i:02d}" for i in range(shared_slug_pool_size)]
    shared_nodes = [f"shared-node-{i:02d}" for i in range(shared_node_pool_size)]

    base_ts = datetime(2026, 5, 24, tzinfo=timezone.utc)

    pages: list[WikiPage] = []
    for t_idx, tenant in enumerate(tenants):
        n_pages = rng.randint(min_pages, max_pages)
        for p_idx in range(n_pages):
            # 60% of the time use a shared id, 40% use a unique id.
            if rng.random() < 0.6:
                pid = rng.choice(shared_ids)
            else:
                pid = f"pg-{t_idx:03d}-{p_idx:03d}-{rng.randint(0, 9999)}"
            if rng.random() < 0.5:
                slug = rng.choice(shared_slugs)
            else:
                slug = f"slug-{t_idx:03d}-{p_idx:03d}"
            if rng.random() < 0.5:
                node = rng.choice(shared_nodes)
            else:
                node = f"node-{t_idx:03d}-{p_idx:03d}"
            ts = base_ts + timedelta(seconds=t_idx * 100 + p_idx)
            pages.append(
                _page(
                    pid,
                    tenant_id=tenant,
                    ontology_node_id=node,
                    slug=slug,
                    created_at=ts,
                )
            )
    return tenants, pages


def _dedup_per_tenant(pages: list[WikiPage]) -> list[WikiPage]:
    """Keep only the last page per (tenant_id, id) — the store does the same."""
    seen: dict[tuple[str, str], WikiPage] = {}
    for p in pages:
        seen[(p.tenant_id, p.id)] = p
    return list(seen.values())


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_property_get_never_crosses_tenants() -> None:
    """For every (tenant_a, page_b from another tenant) pair, get() returns None."""
    rng = random.Random(SEED)
    tenants, pages = _build_random_dataset(rng, num_tenants=20)

    store = InMemoryPageStore()
    for p in pages:
        await store.upsert(p)

    cross_probes = 0
    for tenant_a in tenants:
        for page_b in pages:
            if page_b.tenant_id == tenant_a:
                continue
            # If tenant_a happens to also own a page with this same id,
            # then get() can legitimately return that page — but it
            # must NEVER return page_b itself.
            result = await store.get(tenant_a, page_b.id)
            if result is None:
                cross_probes += 1
                continue
            # Either None or a same-id page that belongs to tenant_a.
            assert result.tenant_id == tenant_a, (
                f"leak: store.get({tenant_a!r}, {page_b.id!r}) "
                f"returned a page with tenant_id={result.tenant_id!r}"
            )
            # The returned page must be the tenant's own copy, not page_b.
            assert result is not page_b
            cross_probes += 1

    # Sanity: the cross-loop actually exercised the store hard.
    assert cross_probes >= 100, (
        f"expected >=100 cross-tenant probes, got {cross_probes}"
    )


@pytest.mark.asyncio
async def test_property_get_by_slug_never_crosses_tenants() -> None:
    """get_by_slug(tenant_a, slug) only returns pages owned by tenant_a (or None)."""
    rng = random.Random(SEED + 1)
    tenants, pages = _build_random_dataset(rng, num_tenants=20)

    store = InMemoryPageStore()
    for p in pages:
        await store.upsert(p)

    cross_probes = 0
    for tenant_a in tenants:
        for page_b in pages:
            if page_b.tenant_id == tenant_a:
                continue
            result = await store.get_by_slug(tenant_a, page_b.slug)
            cross_probes += 1
            if result is None:
                continue
            # The store may return a same-slug page that belongs to tenant_a
            # (collision case), but NEVER page_b itself or any other tenant's page.
            assert result.tenant_id == tenant_a, (
                f"leak: store.get_by_slug({tenant_a!r}, {page_b.slug!r}) "
                f"returned a page with tenant_id={result.tenant_id!r}"
            )
            assert result.slug == page_b.slug

    assert cross_probes >= 100


@pytest.mark.asyncio
async def test_property_list_for_node_never_crosses_tenants() -> None:
    """list_for_node(tenant_a, node_id) returns only pages owned by tenant_a."""
    rng = random.Random(SEED + 2)
    tenants, pages = _build_random_dataset(rng, num_tenants=20)

    store = InMemoryPageStore()
    for p in pages:
        await store.upsert(p)

    # Every node id that appears anywhere in the dataset.
    all_node_ids = sorted({p.ontology_node_id for p in pages})

    probes = 0
    for tenant_a in tenants:
        for node_id in all_node_ids:
            results = await store.list_for_node(tenant_a, node_id)
            probes += 1
            for r in results:
                assert r.tenant_id == tenant_a, (
                    f"leak: list_for_node({tenant_a!r}, {node_id!r}) "
                    f"returned a page with tenant_id={r.tenant_id!r}"
                )
                assert r.ontology_node_id == node_id

    assert probes >= 100


@pytest.mark.asyncio
async def test_property_mark_stale_never_crosses_tenants() -> None:
    """mark_stale on a wrong tenant returns None and never flips the real page."""
    rng = random.Random(SEED + 3)
    tenants, pages = _build_random_dataset(rng, num_tenants=20)
    pages = _dedup_per_tenant(pages)

    store = InMemoryPageStore()
    for p in pages:
        await store.upsert(p)

    # Pages keyed by their owning tenant so we know which pairs are "cross".
    cross_probes = 0
    for tenant_a in tenants:
        for page_b in pages:
            if page_b.tenant_id == tenant_a:
                continue
            # If tenant_a *also* has a page with id == page_b.id (collision),
            # then mark_stale will legitimately flip THAT page; skip those.
            if await store.get(tenant_a, page_b.id) is not None:
                continue

            result = await store.mark_stale(tenant_a, page_b.id)
            cross_probes += 1
            assert result is None, (
                f"leak: mark_stale({tenant_a!r}, {page_b.id!r}) "
                f"returned {result!r} instead of None"
            )
            # The real owner's copy must still be non-stale.
            owner_copy = await store.get(page_b.tenant_id, page_b.id)
            assert owner_copy is not None
            assert owner_copy.is_stale is False, (
                f"leak: mark_stale on wrong tenant flipped is_stale on "
                f"the real page (tenant={page_b.tenant_id}, id={page_b.id})"
            )

    assert cross_probes >= 50, (
        f"expected >=50 cross-tenant mark_stale probes, got {cross_probes}"
    )


@pytest.mark.asyncio
async def test_property_same_id_across_tenants_isolated() -> None:
    """Two tenants with the same page_id stay completely isolated."""
    store = InMemoryPageStore()
    shared_id = "pg-shared"
    page_t1 = _page(
        shared_id,
        tenant_id="tenant-alpha",
        ontology_node_id="node-x",
        slug="alpha-slug",
    )
    page_t2 = _page(
        shared_id,
        tenant_id="tenant-beta",
        ontology_node_id="node-y",
        slug="beta-slug",
    )
    await store.upsert(page_t1)
    await store.upsert(page_t2)

    # get() returns each tenant's own copy.
    got_a = await store.get("tenant-alpha", shared_id)
    got_b = await store.get("tenant-beta", shared_id)
    assert got_a is not None and got_a.tenant_id == "tenant-alpha"
    assert got_a.slug == "alpha-slug"
    assert got_b is not None and got_b.tenant_id == "tenant-beta"
    assert got_b.slug == "beta-slug"

    # A third unrelated tenant sees neither.
    assert await store.get("tenant-gamma", shared_id) is None

    # get_by_slug stays tenant-scoped — alpha's slug is not visible to beta.
    assert await store.get_by_slug("tenant-beta", "alpha-slug") is None
    assert await store.get_by_slug("tenant-alpha", "beta-slug") is None

    # list_for_node stays tenant-scoped — alpha's node is not visible to beta.
    alpha_node_pages = await store.list_for_node("tenant-alpha", "node-x")
    assert {p.tenant_id for p in alpha_node_pages} == {"tenant-alpha"}
    beta_seeing_alpha_node = await store.list_for_node("tenant-beta", "node-x")
    assert beta_seeing_alpha_node == []


@pytest.mark.asyncio
async def test_property_same_slug_across_tenants_isolated() -> None:
    """Two tenants sharing slug + node_id (but with distinct page ids) stay isolated."""
    store = InMemoryPageStore()
    shared_slug = "common-slug"
    shared_node = "common-node"
    page_t1 = _page(
        "pg-001",
        tenant_id="tenant-one",
        ontology_node_id=shared_node,
        slug=shared_slug,
    )
    page_t2 = _page(
        "pg-002",
        tenant_id="tenant-two",
        ontology_node_id=shared_node,
        slug=shared_slug,
    )
    await store.upsert(page_t1)
    await store.upsert(page_t2)

    # get_by_slug returns each tenant's own page.
    found_one = await store.get_by_slug("tenant-one", shared_slug)
    found_two = await store.get_by_slug("tenant-two", shared_slug)
    assert found_one is not None and found_one.tenant_id == "tenant-one"
    assert found_one.id == "pg-001"
    assert found_two is not None and found_two.tenant_id == "tenant-two"
    assert found_two.id == "pg-002"

    # A non-owning tenant sees nothing under that slug.
    assert await store.get_by_slug("tenant-three", shared_slug) is None

    # list_for_node only returns each tenant's own copy.
    one_node_pages = await store.list_for_node("tenant-one", shared_node)
    assert [p.id for p in one_node_pages] == ["pg-001"]
    two_node_pages = await store.list_for_node("tenant-two", shared_node)
    assert [p.id for p in two_node_pages] == ["pg-002"]

    # get() by the other tenant's id is None.
    assert await store.get("tenant-one", "pg-002") is None
    assert await store.get("tenant-two", "pg-001") is None


@pytest.mark.asyncio
async def test_property_concurrent_cross_tenant_upserts_dont_leak() -> None:
    """A concurrent upsert fan-out across many tenants doesn't cross-contaminate."""
    rng = random.Random(SEED + 4)
    tenants, pages = _build_random_dataset(
        rng, num_tenants=15, min_pages=2, max_pages=6
    )
    # Dedup so concurrent upserts with identical keys don't make the assertion
    # ambiguous about which "wins" — we want to assert every page survives.
    pages = _dedup_per_tenant(pages)

    store = InMemoryPageStore()
    await asyncio.gather(*[store.upsert(p) for p in pages])

    # Every page is retrievable by its own tenant.
    for p in pages:
        got = await store.get(p.tenant_id, p.id)
        assert got is not None, f"page {p.id} (tenant {p.tenant_id}) missing"
        assert got == p

    # And invisible to every other tenant — unless that tenant
    # independently upserted a page with the same id (collision case).
    own_keys = {(p.tenant_id, p.id) for p in pages}
    cross_probes = 0
    for p in pages:
        for other in tenants:
            if other == p.tenant_id:
                continue
            cross_probes += 1
            got = await store.get(other, p.id)
            if (other, p.id) in own_keys:
                # The other tenant owns its own same-id page; the store
                # may legitimately return THAT, but it must be tenant-scoped.
                assert got is not None
                assert got.tenant_id == other
            else:
                assert got is None, (
                    f"leak: store.get({other!r}, {p.id!r}) "
                    f"returned a page (tenant={got.tenant_id!r}) "
                    f"that shouldn't exist for that tenant"
                )

    assert cross_probes >= 100

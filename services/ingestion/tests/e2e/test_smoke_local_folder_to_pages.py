"""End-to-end smoke harness (M1-QA-01).

Drives the full ingestion -> ontology -> page-build -> page-store loop on
a synthetic local-folder corpus, using fully-stubbed providers (no
network, no real LLM). The heavy lifting happens once in the
module-scoped ``smoke_result`` fixture in ``conftest.py``; each
``test_*`` here asserts one specific slice so a failure points
straight at the broken seam.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Awaitable, Callable

import pytest

from .conftest import OTHER_TENANT_ID, SMOKE_TENANT_ID, SmokeResult


# Section headers the StubPageWriter / PageBuilder._render_body always emits.
EXPECTED_SECTION_HEADERS = (
    "## Overview",
    "## Key documents",
    "## Related topics",
    "## Metadata",
)

# `PageBuilder._render_body` stamps the body with a wall-clock
# "Last updated: <ISO timestamp>" line. That line is the only
# non-deterministic byte across two pipeline runs over identical
# inputs; we strip it before comparing bodies in the determinism test.
_LAST_UPDATED_RE = re.compile(r"^- Last updated: .*$", re.MULTILINE)


def _strip_last_updated(body: str) -> str:
    return _LAST_UPDATED_RE.sub("- Last updated: <stripped>", body)


# ----------------------------------------------------------------------
# Sanity: the upstream stages actually produced something.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_corpus_was_processed(smoke_result: SmokeResult) -> None:
    """Sanity check: ingestion produced chunks across multiple files."""
    # 7 files materialised on disk.
    assert len(smoke_result.processed) >= 5
    # Every (non-empty) doc produced >=2 chunks given the chunker config,
    # EXCEPT for `tiny.txt` which is intentionally a single-line file (it
    # exercises the rollup-into-parent path in the page pipeline).
    docs_with_chunks = [pd for pd in smoke_result.processed if pd.chunks]
    assert len(docs_with_chunks) >= 4
    for pd in docs_with_chunks:
        first_uri = pd.chunks[0].source_uri
        if first_uri.endswith("tiny.txt"):
            # Tiny doc on purpose - should produce exactly 1 chunk so the
            # pipeline has something to roll into its parent ontology node.
            assert len(pd.chunks) == 1, (
                f"tiny.txt should be a single-chunk doc; got {len(pd.chunks)}"
            )
            continue
        assert len(pd.chunks) >= 2, (
            f"Expected >=2 chunks per doc; got {len(pd.chunks)} for {first_uri}"
        )
    # Aggregated chunk list is what feeds the inducer.
    assert len(smoke_result.all_chunks) >= 10
    # Classifier picked rfi for at least one doc (the RFI-shaped fixtures).
    predicted = {pd.classification.predicted_type for pd in docs_with_chunks}
    assert "rfi" in predicted


@pytest.mark.asyncio
async def test_smoke_ontology_tree_built(smoke_result: SmokeResult) -> None:
    """The inducer returned a non-empty tree."""
    assert smoke_result.tree.nodes, "OntologyInducer produced an empty tree"


# ----------------------------------------------------------------------
# Required assertions per the ticket.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_at_least_one_page_produced(smoke_result: SmokeResult) -> None:
    assert len(smoke_result.pages) >= 1


@pytest.mark.asyncio
async def test_smoke_every_page_retrievable_by_id_and_slug(
    smoke_result: SmokeResult,
) -> None:
    """Every page returned by the pipeline is round-trippable via the store."""
    assert smoke_result.pages, "no pages built - upstream sanity check should have caught this"
    for page in smoke_result.pages:
        by_id = await smoke_result.store.get(SMOKE_TENANT_ID, page.id)
        assert by_id is not None, f"page {page.id} missing from store by id"
        assert by_id.id == page.id

        by_slug = await smoke_result.store.get_by_slug(SMOKE_TENANT_ID, page.slug)
        assert by_slug is not None, (
            f"page {page.id} missing from store by slug {page.slug!r}"
        )
        # Slug uniqueness is not guaranteed by the store contract - two
        # ontology nodes can label-collide and share a slug. We only
        # require that the returned page actually has the looked-up
        # slug (i.e., the store's slug index is functional).
        assert by_slug.slug == page.slug, (
            f"store.get_by_slug returned a page with mismatched slug: "
            f"requested {page.slug!r}, got {by_slug.slug!r}"
        )


@pytest.mark.asyncio
async def test_smoke_body_markdown_has_all_four_sections(
    smoke_result: SmokeResult,
) -> None:
    """Every page's body_markdown is non-empty and contains the four section headers."""
    for page in smoke_result.pages:
        assert page.body_markdown, f"page {page.id} has empty body_markdown"
        for header in EXPECTED_SECTION_HEADERS:
            assert header in page.body_markdown, (
                f"page {page.id} body_markdown missing required header "
                f"{header!r}.\nBody was:\n{page.body_markdown}"
            )


@pytest.mark.asyncio
async def test_smoke_no_page_lists_itself_in_related(
    smoke_result: SmokeResult,
) -> None:
    """Cycle / self-loop guard: no page references itself."""
    for page in smoke_result.pages:
        assert page.id not in page.related_page_ids, (
            f"page {page.id} lists itself in related_page_ids"
        )


@pytest.mark.asyncio
async def test_smoke_tenant_isolation(smoke_result: SmokeResult) -> None:
    """Every page is tagged with the smoke tenant; other tenants can't read it."""
    assert smoke_result.pages
    for page in smoke_result.pages:
        assert page.tenant_id == SMOKE_TENANT_ID, (
            f"page {page.id} has tenant_id {page.tenant_id!r}, "
            f"expected {SMOKE_TENANT_ID!r}"
        )
    # Cross-tenant probe: a real page id, but the wrong tenant, returns None.
    sample_id = smoke_result.pages[0].id
    leaked = await smoke_result.store.get(OTHER_TENANT_ID, sample_id)
    assert leaked is None, (
        f"tenant isolation breach: store.get({OTHER_TENANT_ID!r}, {sample_id!r}) "
        f"returned {leaked!r}"
    )


@pytest.mark.asyncio
async def test_smoke_determinism_across_two_runs(
    smoke_corpus_root: Path,
    run_pipeline_callable: Callable[[Path], Awaitable[SmokeResult]],
    smoke_result: SmokeResult,
) -> None:
    """Running the whole harness twice produces the same page set + bodies.

    Everything in the pipeline is stubbed, so identical inputs MUST yield
    identical page_ids across runs and identical body_markdown modulo the
    one "Last updated: <wall clock>" stamp (the pipeline does not expose
    a `now` override, so that single line legitimately varies between
    runs and is normalised away here).
    """
    second = await run_pipeline_callable(smoke_corpus_root)

    first_ids = {p.id for p in smoke_result.pages}
    second_ids = {p.id for p in second.pages}
    assert first_ids == second_ids, (
        f"page ids differ across runs.\n"
        f"first - second: {sorted(first_ids - second_ids)}\n"
        f"second - first: {sorted(second_ids - first_ids)}"
    )

    first_bodies = {p.id: _strip_last_updated(p.body_markdown) for p in smoke_result.pages}
    second_bodies = {p.id: _strip_last_updated(p.body_markdown) for p in second.pages}
    for page_id in first_ids:
        assert first_bodies[page_id] == second_bodies[page_id], (
            f"body_markdown differs across runs for page {page_id} "
            f"(after stripping the Last updated stamp)"
        )

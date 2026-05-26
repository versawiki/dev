"""HTML viewer router for the local-folder demo.

Three GET routes that render Jinja templates against the api service's
``page_store`` (the one already on ``app.state``). The demo launcher
populates the store before binding the app to a uvicorn server, and also
sets ``app.state.demo_tenant_id`` so the viewer knows which tenant's
pages to surface.

Why mount on the api app rather than a separate one: a single port is
the cleanest demo experience, and the viewer's read path is purely
``page_store`` -> HTML — it doesn't need the api's auth middleware. The
existing JSON routes (``/v1/...``) stay untouched; this just adds three
new templated routes alongside them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt

from versawiki_api.pages_store import PageStore, WikiPageRecord


router = APIRouter()


# ---------------------------------------------------------------------------
# Jinja setup
# ---------------------------------------------------------------------------

_env = Environment(
    loader=PackageLoader("versawiki_demo", "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Markdown renderer — CommonMark + tables, GFM-ish.
_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True}).enable("table")


# ---------------------------------------------------------------------------
# Helpers — pull every page for the demo tenant out of the store
# ---------------------------------------------------------------------------


def _demo_tenant_id(request: Request) -> str:
    tid = getattr(request.app.state, "demo_tenant_id", None)
    if not tid:
        raise HTTPException(
            status_code=503,
            detail="demo viewer not initialised: app.state.demo_tenant_id is missing",
        )
    return tid


def _all_pages_for_tenant(store: PageStore, tenant_id: str) -> list[WikiPageRecord]:
    """Pull every page in the store that belongs to ``tenant_id``.

    The :class:`PageStore` protocol does not expose a "list all" — it
    only exposes per-node listing. For the in-memory store used in the
    demo we reach for the internal ``_pages`` dict directly. If a
    different store is wired in (e.g. Postgres), the caller is expected
    to override ``app.state.demo_pages`` with a precomputed list.
    """
    cached = getattr(store, "_demo_cached_pages", None)
    if isinstance(cached, list):
        return list(cached)

    pages_dict = getattr(store, "_pages", None)
    if isinstance(pages_dict, dict):
        out = [
            page
            for (tid, _pid), page in pages_dict.items()
            if tid == tenant_id
        ]
        out.sort(key=lambda p: (tuple(p.predominant_doc_types) or ("",), p.title.lower()))
        return out
    return []


def _store(request: Request) -> PageStore:
    store = getattr(request.app.state, "page_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="demo viewer not initialised: app.state.page_store is missing",
        )
    return store


# ---------------------------------------------------------------------------
# Grouping + rendering helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PageCard:
    title: str
    slug: str
    summary: str
    doc_types: tuple[str, ...]


def _to_card(page: WikiPageRecord) -> _PageCard:
    summary = page.summary or ""
    if len(summary) > 200:
        summary = summary[:197].rstrip() + "..."
    return _PageCard(
        title=page.title,
        slug=page.slug,
        summary=summary,
        doc_types=tuple(page.predominant_doc_types),
    )


def _group_by_doc_type(pages: Iterable[WikiPageRecord]) -> list[tuple[str, list[_PageCard]]]:
    """Group pages by their primary doc-type for the homepage facets.

    A page's "primary" doc type is the first entry in
    ``predominant_doc_types``. Pages with no doc types land in
    ``Uncategorized``.
    """
    buckets: dict[str, list[_PageCard]] = {}
    for page in pages:
        primary = page.predominant_doc_types[0] if page.predominant_doc_types else "Uncategorized"
        buckets.setdefault(primary, []).append(_to_card(page))

    for cards in buckets.values():
        cards.sort(key=lambda c: c.title.lower())

    return sorted(buckets.items(), key=lambda kv: kv[0].lower())


def _render(template_name: str, **context) -> HTMLResponse:
    template = _env.get_template(template_name)
    return HTMLResponse(template.render(**context))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Homepage: every ingested page, grouped by primary doc type."""
    store = _store(request)
    tenant_id = _demo_tenant_id(request)
    pages = _all_pages_for_tenant(store, tenant_id)
    groups = _group_by_doc_type(pages)
    return _render(
        "home.html",
        groups=groups,
        page_count=len(pages),
        tenant_id=tenant_id,
    )


@router.get("/wiki/{slug}", response_class=HTMLResponse)
async def wiki_page(slug: str, request: Request) -> HTMLResponse:
    """Detail page: rendered markdown + metadata sidebar."""
    store = _store(request)
    tenant_id = _demo_tenant_id(request)
    record = await store.get_by_slug(tenant_id, slug)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no wiki page with slug {slug!r}")

    body_html = _md.render(record.body_markdown or "")

    # Resolve related pages (by stable page_id -> get -> slug + title)
    related: list[dict[str, str]] = []
    for rid in record.related_page_ids:
        rec = await store.get(tenant_id, rid)
        if rec is not None:
            related.append({"slug": rec.slug, "title": rec.title})

    return _render(
        "page.html",
        record=record,
        body_html=body_html,
        related=related,
    )


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query(default="", description="Substring to match in title or summary."),
) -> HTMLResponse:
    """Title + summary substring search (case-insensitive)."""
    store = _store(request)
    tenant_id = _demo_tenant_id(request)

    needle = (q or "").strip().lower()
    pages = _all_pages_for_tenant(store, tenant_id)

    if needle:
        matched = [
            p
            for p in pages
            if needle in p.title.lower() or needle in (p.summary or "").lower()
        ]
    else:
        matched = []

    cards = [_to_card(p) for p in matched]
    return _render(
        "search.html",
        query=q,
        cards=cards,
        has_query=bool(needle),
    )


__all__ = ["router"]

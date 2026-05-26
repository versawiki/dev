"""Tests for the demo viewer router.

Validates the three HTML routes (homepage, page detail, search) and
the 404 path. Uses the seeded fixture from ``conftest.py`` — no real
ingestion or LLM calls.
"""

from __future__ import annotations


def test_homepage_lists_pages_grouped_by_doc_type(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # All three seeded page titles render.
    assert "Concrete Mix RFI" in html
    assert "Rebar Spacing RFI" in html
    assert "Weekly Coordination Meeting" in html

    # Doc-type chips render somewhere on the page.
    assert "rfi" in html
    assert "meeting_minutes" in html

    # Pages are grouped — the home template wraps each group in a
    # `data-doc-type-section="..."` attribute.
    assert 'data-doc-type-section="rfi"' in html
    assert 'data-doc-type-section="meeting_minutes"' in html

    # The two RFI pages should appear in the same section. We assert
    # the section markers exist and that there's exactly one section
    # per distinct doc type.
    assert html.count('data-doc-type-section="rfi"') == 1
    assert html.count('data-doc-type-section="meeting_minutes"') == 1


def test_page_detail_renders_markdown(client):
    resp = client.get("/wiki/concrete-mix-rfi")
    assert resp.status_code == 200
    html = resp.text

    # Title rendered in an <h1> by the template.
    assert "<h1>Concrete Mix RFI</h1>" in html

    # Markdown ## headers in the body become <h2> tags.
    assert "<h2>Overview</h2>" in html
    # Markdown ### headers become <h3> tags.
    assert "<h3>Key questions</h3>" in html

    # Bold (**RFI 042**) becomes <strong>.
    assert "<strong>RFI 042</strong>" in html

    # Metadata sidebar shows the doc type.
    assert "rfi" in html

    # Related-page link to the cross-referenced minutes page.
    assert "/wiki/weekly-coordination-meeting" in html


def test_search_filters_by_title_and_summary(client):
    # Title-match: "concrete" only appears in the first RFI.
    r = client.get("/search", params={"q": "concrete"})
    assert r.status_code == 200
    assert "Concrete Mix RFI" in r.text
    assert "Rebar Spacing RFI" not in r.text
    assert "Weekly Coordination Meeting" not in r.text

    # Summary-match: "Bob" appears in the second RFI's summary.
    r = client.get("/search", params={"q": "Bob"})
    assert r.status_code == 200
    assert "Rebar Spacing RFI" in r.text
    assert "Concrete Mix RFI" not in r.text

    # Case insensitivity.
    r = client.get("/search", params={"q": "REBAR"})
    assert r.status_code == 200
    assert "Rebar Spacing RFI" in r.text

    # No-match returns a "no results" message.
    r = client.get("/search", params={"q": "zzz-no-such-thing-zzz"})
    assert r.status_code == 200
    assert "No results matched" in r.text
    assert "Concrete Mix RFI" not in r.text


def test_page_detail_404_for_unknown_slug(client):
    resp = client.get("/wiki/this-slug-does-not-exist")
    assert resp.status_code == 404

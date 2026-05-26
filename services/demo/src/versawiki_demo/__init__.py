"""Versawiki demo viewer.

The integration layer between `versawiki-ingestion` and `versawiki-api`.
The two production services intentionally don't import from one another;
this one is allowed to import from both because its only job is to wire
them together for the local-folder browse-in-your-browser demo.

Public surface:

  - :mod:`versawiki_demo.cli` — Typer app exposing the ``versawiki-demo``
    console script.
  - :mod:`versawiki_demo.viewer` — FastAPI ``APIRouter`` that renders the
    ingested pages as HTML; mounted by the demo launcher on the api app.
"""

__version__ = "0.1.0"

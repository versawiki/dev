"""Emit the OpenAPI document to stdout.

Used by the web/desktop/mobile build pipelines to regenerate typed
clients::

    python -m versawiki_api._internal.openapi > openapi.json

The script is intentionally minimal: it builds an app with the
default ``Settings()`` and prints ``app.openapi()`` as JSON. CI calls
this and fails the build if the diff against a committed
``openapi.json`` is non-empty (catch contract drift early).
"""

from __future__ import annotations

import json
import sys

from ..app import create_app


def main(argv: list[str] | None = None) -> int:
    del argv  # unused
    app = create_app()
    spec = app.openapi()
    json.dump(spec, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

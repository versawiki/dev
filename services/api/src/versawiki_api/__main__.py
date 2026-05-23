"""`python -m versawiki_api` -> uvicorn launcher.

Usage:
    python -m versawiki_api                  # dev defaults
    python -m versawiki_api --port 9000      # override port
    VW_LOG_LEVEL=DEBUG python -m versawiki_api

For production deployment, prefer a process supervisor invoking
``uvicorn versawiki_api.app:create_app --factory ...`` directly.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .config import get_settings


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="versawiki-api")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument(
        "--reload",
        action="store_true",
        default=settings.env == "dev",
        help="Enable autoreload (default: on in dev).",
    )
    args = parser.parse_args(argv)

    uvicorn.run(
        "versawiki_api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

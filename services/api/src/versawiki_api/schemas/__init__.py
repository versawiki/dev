"""Pydantic v2 request/response models.

One module per resource. ``common`` holds cross-cutting bits (error
envelope, pagination). Keep schemas free of business logic — they are
the wire contract for the web/desktop/mobile/MCP clients.
"""

from __future__ import annotations

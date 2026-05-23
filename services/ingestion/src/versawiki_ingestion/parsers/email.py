# Lifted from project-mcp-server/parsers/email_parser.py per M0-06 audit (REUSE bucket).
# Adapted: project_id -> tenant_id + source_id; removed direct DB writes
# (results return as Pydantic models, persistence is the ingestion service's job).
"""Email Parser - Extracts data from email files.

Handles:
  - .eml files (standard MIME format)
  - .msg files (Outlook format, requires extract-msg)
  - Attachment listing
  - Thread detection
"""

from __future__ import annotations

import email
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .base import BaseParser


class EmailParser(BaseParser):
    document_type = "email"
    supported_extensions = [".eml", ".msg"]
    supported_mime_types = [
        "message/rfc822",
        "application/vnd.ms-outlook",
    ]

    def extract_text(self, file_path: Path) -> str:
        """Extract email body text."""
        if file_path.suffix.lower() == ".msg":
            return self._extract_msg(file_path)

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            msg = email.message_from_file(f)

        return self._get_body(msg)

    def _get_body(self, msg: email.message.Message) -> str:
        """Extract body text from email.Message object."""
        if msg.is_multipart():
            parts = []
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode("utf-8", errors="replace"))
            return "\n".join(parts) if parts else "[No text body found]"
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace")
            return ""

    def _extract_msg(self, file_path: Path) -> str:
        """Extract text from Outlook .msg format."""
        try:
            import extract_msg

            msg = extract_msg.Message(str(file_path))
            return msg.body or ""
        except ImportError:
            return "[Cannot extract .msg file - install extract-msg package]"

    def extract_fields(self, file_path: Path, full_text: str) -> dict[str, Any]:
        fields: dict[str, Any] = {}

        if file_path.suffix.lower() == ".msg":
            return self._extract_msg_fields(file_path, full_text)

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            msg = email.message_from_file(f)

        # Standard headers
        fields["subject"] = msg.get("Subject", "")
        fields["from_address"] = msg.get("From", "")

        to = msg.get("To", "")
        fields["to_addresses"] = [a.strip() for a in to.split(",") if a.strip()]

        cc = msg.get("Cc", "")
        fields["cc_addresses"] = (
            [a.strip() for a in cc.split(",") if a.strip()] if cc else []
        )

        # Date
        date_str = msg.get("Date", "")
        if date_str:
            try:
                dt = parsedate_to_datetime(date_str)
                fields["date"] = dt.isoformat()
            except Exception:
                fields["date"] = date_str

        # Thread ID
        fields["thread_id"] = msg.get("In-Reply-To", "") or msg.get("References", "")

        # Attachments
        has_attachments = False
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                has_attachments = True
                break
        fields["has_attachments"] = "true" if has_attachments else "false"

        return fields

    def _extract_msg_fields(self, file_path: Path, full_text: str) -> dict[str, Any]:
        """Extract fields from Outlook .msg format."""
        try:
            import extract_msg

            msg = extract_msg.Message(str(file_path))
            fields: dict[str, Any] = {
                "subject": msg.subject or "",
                "from_address": msg.sender or "",
                "to_addresses": [
                    a.strip() for a in (msg.to or "").split(";") if a.strip()
                ],
                "cc_addresses": (
                    [a.strip() for a in (msg.cc or "").split(";") if a.strip()]
                    if msg.cc
                    else []
                ),
                "date": str(msg.date) if msg.date else "",
                "has_attachments": "true" if msg.attachments else "false",
            }
            return fields
        except ImportError:
            return {"subject": file_path.stem}

    def get_attachments(self, file_path: Path) -> list[dict[str, Any]]:
        """List attachments in the email (metadata only, not extracted)."""
        if file_path.suffix.lower() == ".msg":
            return self._get_msg_attachments(file_path)

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            msg = email.message_from_file(f)

        attachments: list[dict[str, Any]] = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                attachments.append(
                    {
                        "filename": part.get_filename() or "unnamed",
                        "content_type": part.get_content_type(),
                        "size": len(part.get_payload(decode=True) or b""),
                    }
                )
        return attachments

    def _get_msg_attachments(self, file_path: Path) -> list[dict[str, Any]]:
        try:
            import extract_msg

            msg = extract_msg.Message(str(file_path))
            return [
                {
                    "filename": att.longFilename or att.shortFilename or "unnamed",
                    "size": len(att.data) if att.data else 0,
                }
                for att in msg.attachments
            ]
        except ImportError:
            return []

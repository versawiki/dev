"""Smoke tests for the three concrete parsers shipped with M1.

Each test exercises `parse()` end-to-end (extract_text + extract_fields +
confidence calc) against a tiny fixture supplied by `conftest.py`.

Parser-specific dependencies are guarded: if `openpyxl` is missing the Excel
test is skipped rather than failing at import time.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from versawiki_ingestion.parsers.base import GeneralTextParser, ParseResult
from versawiki_ingestion.parsers.email import EmailParser
from versawiki_ingestion.parsers.excel import ExcelParser


# ----------------------------------------------------------------------
# GeneralTextParser
# ----------------------------------------------------------------------


def test_general_text_parser_parses_plain_text(sample_txt: Path) -> None:
    parser = GeneralTextParser()

    assert parser.can_parse(sample_txt)
    result = parser.parse(sample_txt)

    assert isinstance(result, ParseResult)
    assert result.document_type == "general_document"
    assert "small text fixture" in result.full_text
    assert result.fields["title"] == "note"
    assert 0.0 <= result.confidence <= 1.0


def test_general_text_parser_file_hash_is_stable(tmp_path: Path) -> None:
    p = tmp_path / "h.txt"
    p.write_text("deterministic content", encoding="utf-8")
    h1 = GeneralTextParser.file_hash(p)
    h2 = GeneralTextParser.file_hash(p)
    assert h1 == h2 and len(h1) == 64  # sha256 hex


# ----------------------------------------------------------------------
# EmailParser — operates on the `sample_eml` fixture (a real RFC-822 message).
# ----------------------------------------------------------------------


def test_email_parser_extracts_headers_and_body(sample_eml: Path) -> None:
    parser = EmailParser()

    assert parser.can_parse(sample_eml)
    result = parser.parse(sample_eml)

    assert result.document_type == "email"
    assert "kickoff is at 10am Monday" in result.full_text

    f = result.fields
    assert f["subject"] == "Project kickoff next Monday"
    assert f["from_address"] == "alice@example.com"
    assert "bob@example.com" in f["to_addresses"]
    assert "carol@example.com" in f["to_addresses"]
    assert f["cc_addresses"] == ["dave@example.com"]
    assert f["thread_id"] == "<thread-001@example.com>"
    assert f["has_attachments"] == "false"
    # Date is parsed into ISO-8601.
    assert f["date"].startswith("2026-05-12")


def test_email_parser_get_attachments_empty_for_plain_email(sample_eml: Path) -> None:
    parser = EmailParser()
    assert parser.get_attachments(sample_eml) == []


# ----------------------------------------------------------------------
# ExcelParser — guarded by openpyxl availability.
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    importlib.util.find_spec("openpyxl") is None,
    reason="requires openpyxl on CI",
)
def test_excel_parser_extracts_all_sheets(sample_xlsx: Path) -> None:
    parser = ExcelParser()

    assert parser.can_parse(sample_xlsx)
    result = parser.parse(sample_xlsx)

    assert result.document_type == "general_document"
    assert "=== Sheet: RFI Log ===" in result.full_text
    assert "RFI-001" in result.full_text
    assert "Concrete mix design" in result.full_text
    assert "=== Sheet: Sheet2 ===" in result.full_text
    assert result.fields["title"] == "rfi_log"


@pytest.mark.skipif(
    importlib.util.find_spec("openpyxl") is None,
    reason="requires openpyxl on CI",
)
def test_excel_parser_get_sheet_names(sample_xlsx: Path) -> None:
    parser = ExcelParser()
    assert parser.get_sheet_names(sample_xlsx) == ["RFI Log", "Sheet2"]


@pytest.mark.skipif(
    importlib.util.find_spec("openpyxl") is None,
    reason="requires openpyxl on CI",
)
def test_excel_parser_get_sheet_as_dicts(sample_xlsx: Path) -> None:
    parser = ExcelParser()
    rows = parser.get_sheet_as_dicts(sample_xlsx, sheet_name="RFI Log")
    assert len(rows) == 2
    assert rows[0]["RFI Number"] == "RFI-001"
    assert rows[0]["Status"] == "responded"
    assert rows[1]["Title"] == "Concrete mix design"

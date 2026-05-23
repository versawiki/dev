"""Tests for `ParserRegistry` — three-tier resolution (explicit_type / MIME / extension)."""

from __future__ import annotations

from pathlib import Path

import pytest

from versawiki_ingestion.connectors._models import ResourceRef
from versawiki_ingestion.parsers.base import GeneralTextParser
from versawiki_ingestion.parsers.email import EmailParser
from versawiki_ingestion.parsers.excel import ExcelParser
from versawiki_ingestion.parsers.registry import ParserRegistry


@pytest.fixture
def registry() -> ParserRegistry:
    return ParserRegistry.default()


# ----------------------------------------------------------------------
# MIME resolution — the preferred tier.
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "mime,expected_cls",
    [
        ("text/plain", GeneralTextParser),
        ("text/markdown", GeneralTextParser),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ExcelParser),
        ("application/vnd.ms-excel", ExcelParser),
        ("text/csv", ExcelParser),
        ("message/rfc822", EmailParser),
        ("application/vnd.ms-outlook", EmailParser),
    ],
)
def test_for_mime_resolves_expected_parser(
    registry: ParserRegistry, mime: str, expected_cls: type
) -> None:
    parser = registry.for_mime(mime)
    assert parser is not None
    assert isinstance(parser, expected_cls)


def test_for_mime_is_case_insensitive(registry: ParserRegistry) -> None:
    assert isinstance(registry.for_mime("MESSAGE/RFC822"), EmailParser)


def test_for_mime_unknown_returns_none(registry: ParserRegistry) -> None:
    assert registry.for_mime("application/x-nonsense") is None
    assert registry.for_mime(None) is None
    assert registry.for_mime("") is None


# ----------------------------------------------------------------------
# Extension resolution — the fallback tier.
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "ext,expected_cls",
    [
        (".txt", GeneralTextParser),
        (".md", GeneralTextParser),
        (".log", GeneralTextParser),
        (".xlsx", ExcelParser),
        (".xls", ExcelParser),
        (".csv", ExcelParser),
        (".eml", EmailParser),
        (".msg", EmailParser),
    ],
)
def test_for_extension_resolves_expected_parser(
    registry: ParserRegistry, ext: str, expected_cls: type
) -> None:
    parser = registry.for_extension(ext)
    assert parser is not None
    assert isinstance(parser, expected_cls)


def test_for_extension_is_case_insensitive(registry: ParserRegistry) -> None:
    assert isinstance(registry.for_extension(".XLSX"), ExcelParser)


def test_for_extension_unknown_returns_none(registry: ParserRegistry) -> None:
    assert registry.for_extension(".unknown") is None
    assert registry.for_extension("") is None


# ----------------------------------------------------------------------
# Explicit document_type — tier 1.
# ----------------------------------------------------------------------


def test_for_type_returns_parser_by_document_type(registry: ParserRegistry) -> None:
    assert isinstance(registry.for_type("email"), EmailParser)
    assert isinstance(registry.for_type("general_document"), (GeneralTextParser, ExcelParser))
    assert registry.for_type("not_a_type") is None


# ----------------------------------------------------------------------
# `for_path` and `for_ref` — full three-tier resolution.
# ----------------------------------------------------------------------


def test_for_path_uses_mime_then_extension(registry: ParserRegistry, tmp_path: Path) -> None:
    p = tmp_path / "thing.unknown"
    p.write_text("hi")
    # MIME wins over extension when both are useful.
    assert isinstance(registry.for_path(p, mime="message/rfc822"), EmailParser)
    # Falls through to extension when MIME is unknown.
    p2 = tmp_path / "thing.eml"
    assert isinstance(registry.for_path(p2, mime="application/x-unknown"), EmailParser)
    # Pure extension fallback when no MIME given.
    assert isinstance(registry.for_path(p2), EmailParser)


def test_for_path_explicit_type_wins_over_mime(
    registry: ParserRegistry, tmp_path: Path
) -> None:
    p = tmp_path / "report.xlsx"
    parser = registry.for_path(
        p,
        explicit_type="email",  # nonsensical but tier 1 must win.
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert isinstance(parser, EmailParser)


def test_for_ref_uses_mime_hint(registry: ParserRegistry) -> None:
    ref = ResourceRef(
        tenant_id="t1",
        source_id="s1",
        uri="weird/path/no-extension",
        name="no-extension",
        mime_type="message/rfc822",
    )
    assert isinstance(registry.for_ref(ref), EmailParser)


def test_for_ref_falls_through_to_extension(registry: ParserRegistry) -> None:
    ref = ResourceRef(
        tenant_id="t1",
        source_id="s1",
        uri="path/to/sheet.xlsx",
        name="sheet.xlsx",
        mime_type=None,
    )
    assert isinstance(registry.for_ref(ref), ExcelParser)


def test_for_ref_explicit_type_wins(registry: ParserRegistry) -> None:
    ref = ResourceRef(
        tenant_id="t1",
        source_id="s1",
        uri="path/to/sheet.xlsx",
        name="sheet.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert isinstance(registry.for_ref(ref, explicit_type="email"), EmailParser)

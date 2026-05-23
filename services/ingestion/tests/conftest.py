"""Shared fixtures for the versawiki-ingestion tests."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest


@pytest.fixture
def make_corpus(tmp_path: Path) -> Callable[..., Path]:
    """Returns a factory that materialises a small corpus on disk.

    Usage:
        root = make_corpus({"a.txt": "hello", "sub/b.txt": "world"})
    """

    def _factory(files: dict[str, str | bytes]) -> Path:
        for rel, content in files.items():
            full = tmp_path / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                full.write_bytes(content)
            else:
                full.write_text(content, encoding="utf-8")
        return tmp_path

    return _factory


@pytest.fixture
def sample_eml(tmp_path: Path) -> Path:
    """Write a tiny RFC-822 .eml fixture and return its path."""
    eml = """\
From: alice@example.com
To: bob@example.com, carol@example.com
Cc: dave@example.com
Subject: Project kickoff next Monday
Date: Mon, 12 May 2026 09:30:00 -0400
In-Reply-To: <thread-001@example.com>
Content-Type: text/plain; charset=utf-8

Hi all,

Quick heads-up that the kickoff is at 10am Monday in the conference room.

Thanks,
Alice
"""
    p = tmp_path / "kickoff.eml"
    p.write_text(eml, encoding="utf-8")
    return p


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
    """Write a tiny .xlsx fixture using openpyxl and return its path."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RFI Log"
    ws.append(["RFI Number", "Title", "Status"])
    ws.append(["RFI-001", "Conduit routing question", "responded"])
    ws.append(["RFI-002", "Concrete mix design", "under_review"])
    ws2 = wb.create_sheet("Sheet2")
    ws2.append(["a", "b"])
    ws2.append([1, 2])
    p = tmp_path / "rfi_log.xlsx"
    wb.save(p)
    return p


@pytest.fixture
def sample_txt(tmp_path: Path) -> Path:
    p = tmp_path / "note.txt"
    p.write_text("This is a small text fixture for the base parser.", encoding="utf-8")
    return p

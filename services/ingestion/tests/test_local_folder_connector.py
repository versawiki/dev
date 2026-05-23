"""Tests for `LocalFolderConnector` — covers `list()`, `fetch()`, and `watch()`.

The connector's `watch()` is an async generator that polls on
`poll_interval_s`; we drive it with `anyio` (the project's async runtime) and
collect a bounded number of events with a hard timeout so a misbehaving
implementation can't hang the suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import anyio
import pytest

from versawiki_ingestion.connectors._models import ChangeKind, ResourceRef
from versawiki_ingestion.connectors.local_folder import LocalFolderConnector


# ----------------------------------------------------------------------
# list() + fetch()
# ----------------------------------------------------------------------


def test_list_yields_one_ref_per_file(make_corpus: Callable[..., Path]) -> None:
    root = make_corpus(
        {
            "a.txt": "hello",
            "sub/b.md": "world",
            "sub/nested/c.csv": "x,y\n1,2\n",
            "d.json": '{"k": 1}',
        }
    )
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")

    refs = list(conn.list())
    uris = sorted(r.uri for r in refs)

    assert uris == ["a.txt", "d.json", "sub/b.md", "sub/nested/c.csv"]
    # All refs carry the tenant/source identity and a non-empty etag for change-detection.
    for r in refs:
        assert r.tenant_id == "t1"
        assert r.source_id == "s1"
        assert r.name  # human-readable filename present
        assert r.size_bytes is not None and r.size_bytes >= 0
        assert r.etag  # mtime-size token


def test_list_uses_extension_mime_fallback(make_corpus: Callable[..., Path]) -> None:
    root = make_corpus(
        {
            "note.txt": "This is a small text file with enough content to sniff.",
            "sheet.xlsx": b"PK\x03\x04fake",
        }
    )
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")

    by_uri = {r.uri: r for r in conn.list()}
    # Both files surfaced; mime_type is best-effort (magic, if installed, may
    # return anything from text/plain to application/octet-stream depending on
    # content). The contract is "no crash, ref present, mime_type optional".
    assert {"note.txt", "sheet.xlsx"} <= set(by_uri)
    assert by_uri["note.txt"].extension == ".txt"
    assert by_uri["sheet.xlsx"].extension == ".xlsx"


def test_fetch_returns_exact_bytes(make_corpus: Callable[..., Path]) -> None:
    payload = "the quick brown fox\nover the lazy dog\n"
    root = make_corpus({"pangram.txt": payload})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")

    (ref,) = list(conn.list())
    data = conn.fetch(ref)
    assert data == payload.encode("utf-8")


def test_fetch_refuses_path_traversal(make_corpus: Callable[..., Path]) -> None:
    root = make_corpus({"a.txt": "ok"})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    bad = ResourceRef(
        tenant_id="t1",
        source_id="s1",
        uri="../escape.txt",
        name="escape.txt",
    )
    with pytest.raises(PermissionError):
        conn.fetch(bad)


def test_constructor_rejects_non_directory(tmp_path: Path) -> None:
    f = tmp_path / "not_a_dir.txt"
    f.write_text("hi")
    with pytest.raises(NotADirectoryError):
        LocalFolderConnector(f, tenant_id="t1", source_id="s1")


# ----------------------------------------------------------------------
# watch() — async generator, poll-based
# ----------------------------------------------------------------------


async def _collect_events(conn: LocalFolderConnector, n: int, timeout: float):
    """Consume up to `n` events from `conn.watch()` with an overall timeout."""
    out: list = []

    async def _pump() -> None:
        async for ev in conn.watch():
            out.append(ev)
            if len(out) >= n:
                return

    with anyio.move_on_after(timeout):
        await _pump()
    return out


async def test_watch_emits_added_for_initial_files(
    make_corpus: Callable[..., Path],
) -> None:
    root = make_corpus({"a.txt": "1", "b.txt": "2"})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1", poll_interval_s=0.05)

    events = await _collect_events(conn, n=2, timeout=2.0)

    assert len(events) == 2
    assert all(ev.kind is ChangeKind.ADDED for ev in events)
    assert {ev.ref.uri for ev in events} == {"a.txt", "b.txt"}


async def test_watch_detects_new_file_after_poll(
    make_corpus: Callable[..., Path],
) -> None:
    root = make_corpus({"a.txt": "1"})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1", poll_interval_s=0.05)

    # Start watching; capture the first (ADDED for a.txt), then write a new file
    # and capture the second (ADDED for c.txt).
    events: list = []
    agen = conn.watch()

    async def _consume() -> None:
        async for ev in agen:
            events.append(ev)
            if len(events) == 1:
                # New file appears after the first tick.
                (root / "c.txt").write_text("3", encoding="utf-8")
            if len(events) >= 2:
                return

    with anyio.move_on_after(3.0):
        await _consume()

    assert len(events) >= 2
    kinds_by_uri = {ev.ref.uri: ev.kind for ev in events}
    assert kinds_by_uri.get("a.txt") is ChangeKind.ADDED
    assert kinds_by_uri.get("c.txt") is ChangeKind.ADDED


async def test_watch_detects_modified_and_deleted(
    make_corpus: Callable[..., Path],
) -> None:
    root = make_corpus({"a.txt": "1", "b.txt": "2"})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1", poll_interval_s=0.05)

    events: list = []
    agen = conn.watch()
    seen_initial = 0

    async def _consume() -> None:
        nonlocal seen_initial
        async for ev in agen:
            events.append(ev)
            if ev.kind is ChangeKind.ADDED and seen_initial < 2:
                seen_initial += 1
                if seen_initial == 2:
                    # Mutate b, delete a. Bump mtime explicitly because some
                    # filesystems have 1s mtime resolution and these writes are
                    # within the same second.
                    import os as _os
                    import time as _time

                    (root / "b.txt").write_text("CHANGED", encoding="utf-8")
                    future = _time.time() + 2
                    _os.utime(root / "b.txt", (future, future))
                    (root / "a.txt").unlink()
            if (
                any(e.kind is ChangeKind.MODIFIED for e in events)
                and any(e.kind is ChangeKind.DELETED for e in events)
            ):
                return

    with anyio.move_on_after(4.0):
        await _consume()

    kinds = {(ev.kind, ev.ref.uri) for ev in events}
    assert (ChangeKind.MODIFIED, "b.txt") in kinds
    assert (ChangeKind.DELETED, "a.txt") in kinds

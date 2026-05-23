"""LocalFolderConnector — M1's default source adapter.

Walks a directory tree, yields one `ResourceRef` per file, fetches by reading
the file from disk, and polls for changes by snapshotting `(mtime, size)` per
path and diffing snapshots.

Why mtime+size instead of content hashing for `watch()`: content hashing every
file every poll interval is O(corpus_bytes) per tick; `(mtime, size)` is
O(file_count) and catches every real change short of an attacker deliberately
preserving both. Real dedup at the pipeline level still uses sha256 in
`parsers.base.BaseParser.file_hash`.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Iterator, Optional

import anyio
import structlog

from ._models import ChangeEvent, ChangeKind, ResourceRef

log = structlog.get_logger(__name__)


def _mime_guess(path: Path) -> Optional[str]:
    """Best-effort MIME sniff. Tries python-magic, falls back to extension map."""
    try:
        import magic  # type: ignore[import-not-found]

        return magic.from_file(str(path), mime=True)
    except Exception:
        pass

    ext = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".csv": "text/csv",
        ".eml": "message/rfc822",
        ".msg": "application/vnd.ms-outlook",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".json": "application/json",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
    }.get(ext)


def _etag_from_stat(stat: os.stat_result) -> str:
    """A change-detection token from mtime+size. Cheap and good enough for M1."""
    return f"{stat.st_mtime_ns}-{stat.st_size}"


class LocalFolderConnector:
    """Implements the `Connector` Protocol against a local directory tree."""

    def __init__(
        self,
        root: Path,
        *,
        tenant_id: str,
        source_id: str,
        follow_symlinks: bool = False,
        poll_interval_s: float = 1.0,
    ) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"LocalFolderConnector root is not a directory: {self.root}")
        self.tenant_id = tenant_id
        self.source_id = source_id
        self.follow_symlinks = follow_symlinks
        self.poll_interval_s = poll_interval_s
        # State for `watch()`: uri -> etag from last scan.
        self._etag_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Connector Protocol
    # ------------------------------------------------------------------

    def list(self) -> Iterator[ResourceRef]:
        """Walk `root` recursively, yielding one ResourceRef per regular file."""
        for dirpath, _dirnames, filenames in os.walk(
            self.root, followlinks=self.follow_symlinks
        ):
            for name in filenames:
                full = Path(dirpath) / name
                # Skip non-regular files and broken symlinks.
                try:
                    stat = full.stat()
                except OSError:
                    log.warning("local_folder.stat_failed", path=str(full))
                    continue
                if not os.path.isfile(full):
                    continue
                yield self._ref_for(full, stat)

    def fetch(self, ref: ResourceRef) -> bytes:
        """Read raw bytes for `ref`. Raises FileNotFoundError if missing."""
        path = self._path_for(ref)
        with open(path, "rb") as fh:
            return fh.read()

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        """Poll-based change detection. Yields ADDED / MODIFIED / DELETED events.

        Implementation: snapshot current `(uri -> etag)` each tick; diff against
        the last snapshot; emit one event per delta. The first tick after
        construction emits ADDED for every file currently in the tree (this
        matches the contract — until `watch()` has been called, nothing has
        been "observed", so everything present is "added").
        """
        # First, seed the cache with the current state and emit ADDED for each.
        seeded = False
        while True:
            current: dict[str, ResourceRef] = {}
            for ref in self.list():
                current[ref.uri] = ref
            now = datetime.now(timezone.utc)

            if not seeded:
                for uri, ref in current.items():
                    self._etag_cache[uri] = ref.etag or ""
                    yield ChangeEvent(kind=ChangeKind.ADDED, ref=ref, observed_at=now)
                seeded = True
            else:
                # Detect ADDED and MODIFIED
                for uri, ref in current.items():
                    prior = self._etag_cache.get(uri)
                    if prior is None:
                        self._etag_cache[uri] = ref.etag or ""
                        yield ChangeEvent(kind=ChangeKind.ADDED, ref=ref, observed_at=now)
                    elif prior != (ref.etag or ""):
                        yield ChangeEvent(
                            kind=ChangeKind.MODIFIED,
                            ref=ref,
                            observed_at=now,
                            prior_etag=prior,
                        )
                        self._etag_cache[uri] = ref.etag or ""
                # Detect DELETED
                gone = [uri for uri in self._etag_cache if uri not in current]
                for uri in gone:
                    prior = self._etag_cache.pop(uri)
                    # Reconstruct a minimal ref; we know `name` only from the uri.
                    yield ChangeEvent(
                        kind=ChangeKind.DELETED,
                        ref=ResourceRef(
                            tenant_id=self.tenant_id,
                            source_id=self.source_id,
                            uri=uri,
                            name=Path(uri).name,
                        ),
                        observed_at=now,
                        prior_etag=prior,
                    )

            await anyio.sleep(self.poll_interval_s)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ref_for(self, full: Path, stat: os.stat_result) -> ResourceRef:
        rel = full.resolve().relative_to(self.root)
        uri = rel.as_posix()
        return ResourceRef(
            tenant_id=self.tenant_id,
            source_id=self.source_id,
            uri=uri,
            name=full.name,
            mime_type=_mime_guess(full),
            size_bytes=stat.st_size,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            etag=_etag_from_stat(stat),
        )

    def _path_for(self, ref: ResourceRef) -> Path:
        # ref.uri is relative-to-root POSIX. Resolve back to the underlying path.
        path = (self.root / ref.uri).resolve()
        # Defence-in-depth: refuse to traverse outside `self.root`.
        try:
            path.relative_to(self.root)
        except ValueError as e:
            raise PermissionError(
                f"ref.uri resolves outside connector root: {ref.uri}"
            ) from e
        return path

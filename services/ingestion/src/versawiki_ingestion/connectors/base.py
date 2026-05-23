"""The `Connector` Protocol — the abstraction every source adapter implements.

Three operations only:

1. `list()` — enumerate every resource currently in the source. Synchronous
   iterator because the underlying APIs (filesystem walk; Drive API; OneDrive
   Graph) are naturally pull-based and the worker calling `list()` is itself
   running in an `anyio.to_thread.run_sync` or RQ worker context.
2. `fetch(ref)` — return the raw bytes for one resource. Separate from `list()`
   so the pipeline can decide *whether* to fetch (e.g. skip if `content_hash`
   already in DB).
3. `watch()` — emit `ChangeEvent`s. For M1's `LocalFolderConnector` this is
   poll-based (mtime+size diff). For M2's Drive connector it'll be Drive change
   tokens. Async iterator because real-time sources (push-from-Drive,
   filesystem inotify) are inherently event-shaped.

Why not a single base class with `@abstractmethod`s: a `Protocol` keeps the
adapters fully decoupled (a `LocalFolderConnector` knows nothing about
`gdrive`). Static type checks via `runtime_checkable`; no runtime dependency
on Python ABC machinery.
"""

from __future__ import annotations

from typing import AsyncIterator, Iterator, Protocol, runtime_checkable

from ._models import ChangeEvent, ResourceRef


@runtime_checkable
class Connector(Protocol):
    """Source adapter Protocol. Every connector under `connectors/` implements this."""

    tenant_id: str
    source_id: str

    def list(self) -> Iterator[ResourceRef]:
        """Enumerate every resource currently visible in the source.

        Order is not specified; the pipeline does its own ordering. Implementations
        must be re-entrant (calling `list()` twice yields the same set on a
        quiescent source).
        """
        ...

    def fetch(self, ref: ResourceRef) -> bytes:
        """Return the raw bytes of one resource.

        Implementations should raise `FileNotFoundError` (or a connector-specific
        subclass) for a `ref` that no longer exists. The pipeline retries on
        transient failures classified as retryable by the connector.
        """
        ...

    def watch(self) -> AsyncIterator[ChangeEvent]:
        """Yield change events as resources are added / modified / deleted.

        For poll-based connectors, this is implemented as an async generator
        that sleeps `poll_interval_s` between scans. For event-based connectors
        (M2+), this wraps a webhook or change-token cursor. The async iterator
        is consumed by the ingestion worker; cancellation is via the worker's
        task cancellation.
        """
        ...

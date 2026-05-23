"""Queue + worker indirection.

In production, ingestion jobs run on RQ workers (Redis-backed; see the stack
lock in DECISIONS.md). In tests we don't need Redis to validate the pipeline
flow — `InProcessQueue` is a tiny in-memory dict that satisfies the same
`Queue` Protocol and lets `test_worker_inprocess.py` exercise enqueue +
run_job without any IO.

When RQ comes online (a later ticket), `RedisQueue` will plug in alongside
`InProcessQueue` and the call-sites will stay the same.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol

from .models import IngestionJob


class _Queue(Protocol):
    """The queue surface the worker needs."""

    def put(self, job: IngestionJob, payload: dict[str, Any]) -> None: ...
    def get(self, job_id: str) -> Optional[tuple[IngestionJob, dict[str, Any]]]: ...


class InProcessQueue(_Queue):
    """Test-only in-memory queue.

    Stores `(IngestionJob, payload)` keyed by `job_id`. `payload` carries
    whatever the worker needs to actually run — e.g. a `ResourceRef` dict, a
    connector ref, etc. Kept payload-shape opaque to the queue.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[IngestionJob, dict[str, Any]]] = {}

    def put(self, job: IngestionJob, payload: dict[str, Any]) -> None:
        self._store[job.job_id] = (job, dict(payload))

    def get(self, job_id: str) -> Optional[tuple[IngestionJob, dict[str, Any]]]:
        return self._store.get(job_id)

    def __len__(self) -> int:
        return len(self._store)


def enqueue_ingest(
    queue: _Queue,
    *,
    tenant_id: str,
    source_id: str,
    resource_uri: str,
    payload: Optional[dict[str, Any]] = None,
) -> str:
    """Enqueue an ingest job. Returns the job_id.

    The `payload` is whatever the worker side needs to look up the resource
    (a `ResourceRef` dict + connector type, typically). The queue is
    payload-agnostic.
    """
    job = IngestionJob(
        job_id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        source_id=source_id,
        resource_uri=resource_uri,
        enqueued_at=datetime.now(timezone.utc),
    )
    queue.put(job, payload or {})
    return job.job_id


async def run_job(
    queue: _Queue,
    job_id: str,
    *,
    runner: Callable[[IngestionJob, dict[str, Any]], Awaitable[Any]],
) -> Any:
    """Pull job_id off the queue and run it via `runner`.

    `runner` is a callable that takes `(job, payload)` and returns whatever
    the test wants to assert on (e.g. a list of `ChunkRecord`). Keeping the
    runner injectable means this module has zero knowledge of how documents
    are processed — that's the test's (or production worker's) concern.
    """
    item = queue.get(job_id)
    if item is None:
        raise KeyError(f"job {job_id!r} not found in queue")
    job, payload = item
    return await runner(job, payload)

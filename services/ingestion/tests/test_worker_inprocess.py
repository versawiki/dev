"""Tests for the in-process queue + runner.

The production worker uses RQ + Redis; these tests prove the queue
*interface* round-trips end-to-end with an `InProcessQueue` stand-in so we can
exercise the pipeline without spinning up Redis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from versawiki_ingestion.chunking import Chunker
from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
from versawiki_ingestion.embedding import StubEmbeddingProvider
from versawiki_ingestion.parsers.registry import ParserRegistry
from versawiki_ingestion.pipeline import (
    ChunkRecord,
    InProcessQueue,
    IngestionJob,
    enqueue_ingest,
    process_document,
    run_job,
)


def test_enqueue_returns_job_id_and_stores_in_queue() -> None:
    queue = InProcessQueue()
    job_id = enqueue_ingest(
        queue,
        tenant_id="t1",
        source_id="s1",
        resource_uri="notes.txt",
        payload={"hello": "world"},
    )
    assert isinstance(job_id, str) and len(job_id) >= 16
    assert len(queue) == 1
    got = queue.get(job_id)
    assert got is not None
    job, payload = got
    assert job.tenant_id == "t1"
    assert job.source_id == "s1"
    assert job.resource_uri == "notes.txt"
    assert payload == {"hello": "world"}


@pytest.mark.asyncio
async def test_run_job_invokes_runner_with_job_and_payload() -> None:
    queue = InProcessQueue()
    job_id = enqueue_ingest(
        queue,
        tenant_id="t1",
        source_id="s1",
        resource_uri="x.txt",
        payload={"k": 42},
    )
    captured: dict[str, Any] = {}

    async def runner(job: IngestionJob, payload: dict[str, Any]) -> str:
        captured["job_id"] = job.job_id
        captured["payload"] = payload
        return "ok"

    result = await run_job(queue, job_id, runner=runner)
    assert result == "ok"
    assert captured["job_id"] == job_id
    assert captured["payload"] == {"k": 42}


@pytest.mark.asyncio
async def test_run_job_round_trip_with_real_pipeline(
    make_corpus: Callable[..., Path],
) -> None:
    """Enqueue, then run a runner that actually ingests a file via process_document."""
    root = make_corpus({"doc.txt": "the quick brown fox " * 200})
    conn = LocalFolderConnector(root, tenant_id="t1", source_id="s1")
    (ref,) = list(conn.list())

    queue = InProcessQueue()
    job_id = enqueue_ingest(
        queue,
        tenant_id=ref.tenant_id,
        source_id=ref.source_id,
        resource_uri=ref.uri,
        payload={"ref_uri": ref.uri},
    )

    async def runner(job: IngestionJob, payload: dict[str, Any]) -> list[ChunkRecord]:
        # Re-resolve the ref from the connector via the URI in the payload.
        (resolved,) = [r for r in conn.list() if r.uri == payload["ref_uri"]]
        return await process_document(
            resolved,
            connector=conn,
            parser_registry=ParserRegistry.default(),
            chunker=Chunker(),
            embedding_provider=StubEmbeddingProvider(),
        )

    records = await run_job(queue, job_id, runner=runner)
    assert records
    assert all(r.embedding is not None for r in records)


@pytest.mark.asyncio
async def test_run_job_raises_on_unknown_job() -> None:
    queue = InProcessQueue()

    async def never_called(job: IngestionJob, payload: dict[str, Any]) -> None:
        raise AssertionError("runner should not be called for missing job")

    with pytest.raises(KeyError):
        await run_job(queue, "no-such-id", runner=never_called)

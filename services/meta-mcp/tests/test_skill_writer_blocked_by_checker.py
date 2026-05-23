"""LOAD-BEARING PRIVACY TEST for M1-MCP-03.

If this test passes when it shouldn't, every other test in this ticket
is wrong by transitive failure. The privacy gate is the whole point of
the ticket; nothing else matters if the gate doesn't hold.

We construct a stub LLM that returns markdown with content that MUST
be rejected by the checker (a forbidden field name, an embedded email,
a raw count, an SSN-shape, a URL, a long pasted-document-like token).
For each poisoned variant we assert:

  1. No file is created under `skills_root/<domain>/`.
  2. A rejection record IS appended to the rejections audit log.
  3. The rejection record contains ONLY `{payload_hash, reason_code,
     stage, domain, kind, rejected_at_utc}` — never the offending body
     bytes.
  4. The rejection's `payload_hash` is the sha256 of the poisoned body.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from versawiki_meta_mcp.schema.observation import (
    DomainObservationEnvelope,
    NamingConvention,
)
from versawiki_meta_mcp.skills.aggregator import (
    SignatureAggregator,
    SignatureGroup,
)
from versawiki_meta_mcp.skills.pipeline import (
    SkillWritingOutcome,
    SkillWritingPipeline,
)
from versawiki_meta_mcp.skills.thresholds import (
    SkillWriteThreshold,
    SkillWriteThresholds,
)
from versawiki_meta_mcp.store.file_store import FileMetaStore


def _run(awaitable):
    return asyncio.run(awaitable)


class _PoisonLLMWriter:
    """Returns a fixed poisoned markdown body regardless of input."""

    def __init__(self, body: str) -> None:
        self._body = body

    def write(self, group: SignatureGroup) -> str:  # noqa: D401, ARG002
        return self._body


async def _seed_three_tenants(meta_store: FileMetaStore, n_per_tenant: int = 10) -> None:
    """Seed enough observations to cross the threshold for (AEC, naming-convention)."""

    tenants = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    ]
    base = "abcdefab-cdef-4abc-9abc-abcdefab"
    for t_idx, tenant in enumerate(tenants):
        for i in range(n_per_tenant):
            payload = NamingConvention(
                applies_to="drawing_number",
                template="<phase>-<discipline>-<sequence>",
                token_vocabulary=["phase", "discipline", "sequence"],
                sample_count_bucket="51-200",
                adherence_rate=0.93,
            )
            event_id = f"{base}{t_idx:02x}{i:02x}"
            env = DomainObservationEnvelope(
                event_id=event_id,
                schema_version="1.0.0",
                observed_at_utc=datetime.now(timezone.utc),
                tenant_anon_id=tenant,
                opt_out_flag=False,
                domain_signature_id=None,
                payload=payload,
            )
            await meta_store.write_observation(env)


def _low_threshold() -> SkillWriteThresholds:
    return SkillWriteThresholds(
        default=SkillWriteThreshold(
            min_distinct_tenants=2, min_observations=3, confidence_floor=0.0
        )
    )


POISONED_BODIES: List[tuple[str, str]] = [
    (
        "forbidden_field_name",
        "## When to apply\n\nThe pattern is keyed by email when present.\n",
    ),
    (
        "embedded_email",
        "## When to apply\n\nApply when the contact alice@example.com appears.\n",
    ),
    (
        "raw_count",
        "## When to apply\n\nWe observed this 1273 times across tenants.\n",
    ),
    (
        "ssn",
        "## When to apply\n\nObserved id 123-45-6789 in the corpus.\n",
    ),
    (
        "url",
        "## When to apply\n\nPattern shows up at https://customer.example.com/secret.\n",
    ),
    (
        "long_token",
        "## When to apply\n\nPasted: " + ("x" * 260) + "\n",
    ),
]


@pytest.mark.parametrize(
    "name,poisoned_body",
    POISONED_BODIES,
    ids=[n for n, _ in POISONED_BODIES],
)
def test_checker_rejects_skill_text_and_no_file_is_written(
    tmp_path: Path, name: str, poisoned_body: str
) -> None:
    meta_root = tmp_path / "meta"
    skills_root = tmp_path / "skills"
    store = FileMetaStore(meta_root)
    _run(_seed_three_tenants(store))

    aggregator = SignatureAggregator(meta_store=store, thresholds=_low_threshold())
    pipeline = SkillWritingPipeline(
        aggregator=aggregator,
        llm_writer=_PoisonLLMWriter(poisoned_body),
        skills_root=skills_root,
    )

    results = _run(pipeline.run())

    assert len(results) == 1, f"expected one crossing group, got {len(results)}"
    result = results[0]

    assert result.outcome == SkillWritingOutcome.CHECKER_REJECTED, (
        f"poison body {name!r} should have been rejected by checker, "
        f"got {result.outcome}"
    )

    aec_dir = skills_root / "AEC"
    if aec_dir.exists():
        leaked = [p for p in aec_dir.iterdir() if p.is_file()]
        assert not leaked, f"poison body {name!r} leaked file(s): {leaked}"

    audit_path = skills_root / "_rejections.jsonl"
    assert audit_path.exists(), "rejection audit log must exist"
    raw_lines = [
        line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(raw_lines) == 1, (
        f"expected exactly one rejection line, got {len(raw_lines)}: {raw_lines!r}"
    )
    record = json.loads(raw_lines[0])

    assert set(record.keys()) == {
        "payload_hash",
        "reason_code",
        "stage",
        "domain",
        "kind",
        "rejected_at_utc",
    }, f"poison body {name!r}: unexpected keys: {set(record.keys())}"

    expected_hash = hashlib.sha256(poisoned_body.encode("utf-8")).hexdigest()
    assert record["payload_hash"] == expected_hash, (
        f"poison body {name!r}: hash mismatch — audit must hash the actual body"
    )

    raw_audit_bytes = audit_path.read_bytes()
    if name == "embedded_email":
        forbidden_substring = b"alice@example.com"
    elif name == "url":
        forbidden_substring = b"customer.example.com"
    elif name == "ssn":
        forbidden_substring = b"123-45-6789"
    elif name == "raw_count":
        forbidden_substring = b"1273"
    elif name == "forbidden_field_name":
        forbidden_substring = b"keyed by email"
    elif name == "long_token":
        forbidden_substring = b"x" * 50
    else:
        forbidden_substring = poisoned_body.encode("utf-8")
    assert forbidden_substring not in raw_audit_bytes, (
        f"poison body {name!r} bytes leaked into audit log"
    )

    assert result.chain_result is not None
    assert result.chain_result.passed is False
    assert result.chain_result.failed_stage is not None
    assert result.chain_result.failed_reason is not None
    assert result.chain_result.payload_hash == expected_hash


def test_no_path_writes_file_ahead_of_check(tmp_path: Path) -> None:
    """The pipeline has one file-writing path, and it sits AFTER the gate."""

    meta_root = tmp_path / "meta"
    skills_root = tmp_path / "skills"
    store = FileMetaStore(meta_root)
    _run(_seed_three_tenants(store))

    aggregator = SignatureAggregator(meta_store=store, thresholds=_low_threshold())

    class _EmptyLLM:
        def write(self, group: SignatureGroup) -> str:  # noqa: ARG002
            return ""

    pipeline = SkillWritingPipeline(
        aggregator=aggregator, llm_writer=_EmptyLLM(), skills_root=skills_root
    )
    results = _run(pipeline.run())
    assert len(results) == 1
    assert results[0].outcome in (
        SkillWritingOutcome.DRAFT_INVALID,
        SkillWritingOutcome.CHECKER_REJECTED,
    )
    aec_dir = skills_root / "AEC"
    if aec_dir.exists():
        assert not list(aec_dir.glob("*.md"))

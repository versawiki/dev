"""AgentRunner tests that don't need the actual Claude SDK.

We verify:
- Spend-cap pre-flight short-circuits with the right error
- Audit rows land in the expected order
- The runner doesn't try to call the SDK when pre-flight fails

A second file (`test_agent_runner_with_mocked_sdk.py`) would mock the SDK
itself to test the happy path; that's an obvious next step but is gated
on installing `claude-agent-sdk` in CI.
"""

from __future__ import annotations

import pytest

from versawiki_orchestrator.agent import AgentRunner, ORCHESTRATOR_SYSTEM_PROMPT
from versawiki_orchestrator.audit import AuditLog
from versawiki_orchestrator.config import Settings
from versawiki_orchestrator.events.types import TickEvent
from versawiki_orchestrator.spending import SpendingTracker


def test_system_prompt_contains_critical_constraints() -> None:
    p = ORCHESTRATOR_SYSTEM_PROMPT
    # Hard rules from the spec.
    assert "NEVER push to `main`" in p
    assert "branch named `vw-agent/<ticket-id>`" in p
    assert "STATUS.md" in p
    assert "ONE ticket per run" in p
    assert "pipeline.py" in p  # privacy-critical file mention


async def test_pre_flight_blocks_when_daily_cap_hit(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    spending = SpendingTracker(tmp_audit, settings)
    # Push spend past daily cap (1.0 in conftest).
    spending.record(
        amount_usd=1.5, model="claude-sonnet-4-6",
        input_tokens=0, output_tokens=0, run_id="seed",
    )

    runner = AgentRunner(
        settings=settings,
        audit=tmp_audit,
        spending=spending,
        pr_callback=None,
    )

    result = await runner.handle(TickEvent())
    assert not result.success
    assert result.error == "spend_cap:daily_cap_hit"
    assert "Daily cap reached" in result.summary

    # The audit log should show preflight but NOT run_started — pre-flight
    # blocking must short-circuit before we try to spin up the SDK.
    types = [e.event_type for e in tmp_audit.tail(20)]
    assert "run_preflight" in types
    assert "run_started" not in types


async def test_pre_flight_passes_then_run_started_logged(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    """When spend cap is fine and the SDK isn't installed in this test env,
    the runner records run_started, fails at SDK import inside _do_run, and
    still produces a clean RunResult with finished_at_ns set and an error."""
    spending = SpendingTracker(tmp_audit, settings)
    runner = AgentRunner(
        settings=settings,
        audit=tmp_audit,
        spending=spending,
        pr_callback=None,
    )
    result = await runner.handle(TickEvent())
    # If the SDK happens to be installed in the test environment, the run
    # would actually try to talk to Claude. Both paths must produce a
    # well-formed RunResult.
    assert result.finished_at_ns >= result.started_at_ns
    types = [e.event_type for e in tmp_audit.tail(20)]
    assert "run_preflight" in types
    assert "run_started" in types
    assert "run_finished" in types

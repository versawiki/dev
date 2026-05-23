"""SpendingTracker tests."""

from __future__ import annotations

import pytest

from versawiki_orchestrator.audit import AuditLog
from versawiki_orchestrator.config import Settings
from versawiki_orchestrator.spending import SpendingTracker


def test_under_caps_allows(tmp_audit: AuditLog, settings: Settings) -> None:
    st = SpendingTracker(tmp_audit, settings)
    decision = st.evaluate()
    assert decision.allowed
    assert decision.reason == "under_caps"
    assert decision.spent_today_usd == 0.0


def test_daily_cap_trips_first(tmp_audit: AuditLog, settings: Settings) -> None:
    # settings.daily_spend_cap_usd = 1.0 from conftest
    st = SpendingTracker(tmp_audit, settings)
    st.record(amount_usd=0.99, model="claude-sonnet-4-6", input_tokens=100, output_tokens=50, run_id="r1")
    assert st.evaluate().allowed
    st.record(amount_usd=0.05, model="claude-sonnet-4-6", input_tokens=10, output_tokens=5, run_id="r2")
    d = st.evaluate()
    assert not d.allowed
    assert d.reason == "daily_cap_hit"
    assert d.window_tripped == "daily"
    assert "Daily cap reached" in d.summary


def test_weekly_cap_trips_before_monthly(tmp_audit: AuditLog, settings: Settings) -> None:
    # Bump daily so weekly trips first; weekly cap = 5.0
    settings = settings.model_copy(update={"daily_spend_cap_usd": 100.0})
    st = SpendingTracker(tmp_audit, settings)
    st.record(amount_usd=6.0, model="claude-sonnet-4-6", input_tokens=1, output_tokens=1, run_id="r")
    d = st.evaluate()
    assert not d.allowed
    assert d.reason == "weekly_cap_hit"


def test_estimate_usd_sonnet(tmp_audit: AuditLog, settings: Settings) -> None:
    st = SpendingTracker(tmp_audit, settings)
    # 1M input tokens × $3 + 1M output × $15
    assert st.estimate_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_estimate_usd_opus(tmp_audit: AuditLog, settings: Settings) -> None:
    st = SpendingTracker(tmp_audit, settings)
    assert st.estimate_usd("claude-opus-4-6", 1_000_000, 0) == pytest.approx(15.0)
    assert st.estimate_usd("claude-opus-4-6", 0, 1_000_000) == pytest.approx(75.0)


def test_estimate_usd_haiku(tmp_audit: AuditLog, settings: Settings) -> None:
    st = SpendingTracker(tmp_audit, settings)
    assert st.estimate_usd("claude-haiku-4-5", 1_000_000, 0) == pytest.approx(0.8)


def test_unknown_model_falls_back_to_sonnet_rates(
    tmp_audit: AuditLog, settings: Settings
) -> None:
    st = SpendingTracker(tmp_audit, settings)
    # No "opus" or "haiku" in name -> sonnet rates.
    assert st.estimate_usd("claude-future-model", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_record_appends_to_audit(tmp_audit: AuditLog, settings: Settings) -> None:
    st = SpendingTracker(tmp_audit, settings)
    st.record(amount_usd=0.42, model="claude-sonnet-4-6", input_tokens=10, output_tokens=20, run_id="abc")
    rows = tmp_audit.tail()
    assert len(rows) == 1
    assert rows[0].event_type == "spend_recorded"
    assert rows[0].payload["amount_usd"] == pytest.approx(0.42)
    assert rows[0].payload["run_id"] == "abc"

"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from versawiki_orchestrator.audit import AuditLog
from versawiki_orchestrator.config import Settings


@pytest.fixture
def tmp_audit(tmp_path: Path) -> AuditLog:
    log = AuditLog(tmp_path / "audit.sqlite")
    try:
        yield log
    finally:
        log.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A Settings instance with all required secrets stubbed.

    We don't load from env at construction time; instead build directly
    with the test values. Anything not set here uses the production
    defaults from `Settings`.
    """
    return Settings(
        mode="observe",
        repo_workdir=tmp_path / "repo",
        anthropic_api_key=SecretStr("sk-test"),
        gh_pat=SecretStr("ghp-test"),
        control_api_bearer=SecretStr("test-bearer-token-do-not-use-in-prod"),
        audit_db_path=tmp_path / "audit.sqlite",
        # Tiny caps so the cap tests don't depend on real spending.
        daily_spend_cap_usd=1.0,
        weekly_spend_cap_usd=5.0,
        monthly_spend_cap_usd=20.0,
        tick_interval_seconds=1,
        smtp_host="",
    )

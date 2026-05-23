"""Runtime configuration loaded from environment.

All settings live here so the rest of the codebase doesn't reach into
`os.environ` directly. `Settings()` reads from process env at construction
time; tests pass an explicit instance instead.

The defaults are aimed at the soak-test phase from the spec — observe-only
mode, $20/day cap, Sonnet 4.6, escalation by email.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All orchestrator configuration. Loaded from environment by default."""

    model_config = SettingsConfigDict(
        env_prefix="VW_ORCH_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Mode + safety
    # ------------------------------------------------------------------
    # `observe` is the spec's recommended first 48 hours: agent runs but
    # the PR writer logs intended actions instead of pushing.
    mode: Literal["observe", "act"] = "observe"

    # The agent works on a clone of versawiki/dev. This is where the
    # local clone lives.
    repo_workdir: Path = Path("/var/lib/versawiki-orchestrator/repo")

    # Branch that's protected and must never be force-pushed.
    main_branch: str = "main"

    # ------------------------------------------------------------------
    # Anthropic + agent
    # ------------------------------------------------------------------
    anthropic_api_key: SecretStr = SecretStr("")

    # Default model used for routine runs. Spec recommends Sonnet; agent
    # can request an Opus escalation per-run if its prompt flags
    # "needs reasoning depth".
    model: str = "claude-sonnet-4-6"
    opus_model: str = "claude-opus-4-6"
    max_turns_per_run: int = 60

    # Per-run hard cap (USD). Even with the daily cap intact, a runaway
    # single run will be killed when it exceeds this.
    spend_cap_usd_per_run: float = 5.0

    # ------------------------------------------------------------------
    # Spending caps (USD)
    # ------------------------------------------------------------------
    daily_spend_cap_usd: float = 20.0
    weekly_spend_cap_usd: float = 100.0
    monthly_spend_cap_usd: float = 350.0

    # ------------------------------------------------------------------
    # GitHub
    # ------------------------------------------------------------------
    gh_pat: SecretStr = SecretStr("")
    gh_owner: str = "versawiki"
    gh_repo: str = "dev"

    # ------------------------------------------------------------------
    # Control API
    # ------------------------------------------------------------------
    control_api_host: str = "0.0.0.0"
    control_api_port: int = 8088
    # Bearer token that callers (Josh's phone, future admin UI) must pass.
    control_api_bearer: SecretStr = SecretStr("")

    # ------------------------------------------------------------------
    # Escalation: email via SMTP
    # ------------------------------------------------------------------
    escalation_to: str = "joshuafausset@hotmail.com"
    escalation_from: str = "orchestrator@versawiki.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_use_starttls: bool = True

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    audit_db_path: Path = Path("/var/lib/versawiki-orchestrator/audit.sqlite")

    # ------------------------------------------------------------------
    # Tick scheduler
    # ------------------------------------------------------------------
    tick_interval_seconds: int = 300

    # ------------------------------------------------------------------
    # Pricing — used by spend tracker. Per-1M-token rates as of the spec.
    # These are conservative defaults; refresh from Anthropic's pricing
    # page periodically.
    # ------------------------------------------------------------------
    price_sonnet_input_per_mtok: float = 3.0
    price_sonnet_output_per_mtok: float = 15.0
    price_opus_input_per_mtok: float = 15.0
    price_opus_output_per_mtok: float = 75.0
    price_haiku_input_per_mtok: float = 0.8
    price_haiku_output_per_mtok: float = 4.0


def load_settings() -> Settings:
    """Construct a Settings instance from the current process env."""
    return Settings()

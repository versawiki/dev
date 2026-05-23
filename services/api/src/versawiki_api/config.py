"""Application settings. All env-driven; loaded once and cached.

Prefix is ``VW_`` so a deployment env file looks like::

    VW_ENV=prod
    VW_DATABASE_URL=postgresql+asyncpg://...
    VW_REDIS_URL=rediss://...
    VW_CORS_ORIGINS=https://app.versawiki.io,https://desktop.versawiki.io

`pydantic-settings` v2 reads these on instantiation. We use
``lru_cache`` so the settings object is constructed exactly once per
process; tests can clear it via ``get_settings.cache_clear()``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration.

    Anything that varies between dev / staging / prod or between
    deploys belongs here. Secrets (API keys, DSNs) are read from env;
    we never commit a populated ``.env``.
    """

    model_config = SettingsConfigDict(
        env_prefix="VW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- runtime / server ----
    env: Literal["dev", "test", "staging", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = False  # JSON logs in prod; pretty in dev

    # ---- HTTP surface ----
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Allow-list for browser clients.",
    )

    # ---- data layer ----
    # ``database_url`` is the canonical async-DSN consumed by BE-03's
    # SQLAlchemy engine factory (driver: asyncpg). The legacy ``db_url``
    # remains as a back-compat shim so callers that referenced it
    # before BE-03 still build, but every new caller should reach for
    # ``database_url``.
    database_url: str = "postgresql+asyncpg://localhost/versawiki"
    db_url: str = "postgresql+psycopg://localhost/versawiki"
    db_pool_size: int = 10
    db_pool_max_overflow: int = 20
    db_echo: bool = False

    # Password used when the provisioner creates the per-tenant role's
    # initial credentials. In production the provisioner generates a
    # one-shot password per tenant; this default exists so unit tests
    # render deterministic SQL.
    tenant_role_password_bytes: int = 32

    # ---- queue / cache (consumed by BE-02 rate limiting + ingestion workers) ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- LLM providers (consumed by ingestion + meta-MCP) ----
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ---- service identity ----
    service_name: str = "versawiki-api"
    service_version: str = "0.1.0"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Accept comma-separated env var or a JSON list."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value  # let pydantic parse as JSON list
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Use as a FastAPI dependency."""
    return Settings()

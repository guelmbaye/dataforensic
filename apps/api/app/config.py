"""Application configuration.

All configuration is environment based (see .env.example at the repository root).
Secrets are never hardcoded and never logged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Order matters: pydantic-settings lets later files win, so the repo
        # root comes first and the service-local .env overrides it. Running the
        # API from apps/api therefore picks up SQLite instead of the Compose
        # PostgreSQL hostname, which only resolves inside Docker.
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    app_name: str = "DATAFORENSIC AI"
    environment: Literal["local", "demo", "ci", "production"] = "local"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    public_app_url: str = "http://localhost:3000"

    # --- Persistence -----------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./dataforensic.db"
    db_echo: bool = False

    # --- DataHub ---------------------------------------------------------
    datahub_url: str | None = None
    datahub_token: str | None = None
    datahub_mcp_url: str | None = None
    # auto  : probe DataHub, fall back to the deterministic fixture graph
    # live  : require a real DataHub, never fall back
    # fixture: always use the local deterministic graph (clearly labelled in the API)
    datahub_mode: Literal["auto", "live", "fixture"] = "auto"
    datahub_timeout_seconds: float = 15.0
    datahub_fixture_path: str = "datahub/seed/showcase-ecommerce-demo.json"
    datahub_memory_store_path: str = ".local/datahub-fixture-memory.json"
    datahub_writeback_enabled: bool = True

    # --- Scenarios -------------------------------------------------------
    scenarios_path: str = "scenarios"
    default_scenario_id: str = "revenue-collapse"

    # --- LLM (optional) --------------------------------------------------
    # When llm_provider == "none" the agent runs its deterministic reasoning
    # engine only. The deterministic engine is ALWAYS the authority for the
    # final root cause: the LLM proposes, the application validates.
    llm_provider: Literal["none", "anthropic", "openai"] = "none"
    llm_model: str = "claude-sonnet-4-5"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_max_tokens: int = 2000
    llm_timeout_seconds: float = 60.0

    # --- Agent policy ----------------------------------------------------
    agent_max_iterations: int = 16
    agent_lookback_minutes: int = 720
    agent_lineage_depth: int = 4
    confidence_confirm_threshold: float = 0.85
    confidence_support_threshold: float = 0.60
    confidence_reject_threshold: float = 0.30
    allow_real_remediation: bool = False

    # --- Derived helpers -------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def fixture_file(self) -> Path:
        p = Path(self.datahub_fixture_path)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def memory_store_file(self) -> Path:
        p = Path(self.datahub_memory_store_path)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def scenarios_dir(self) -> Path:
        p = Path(self.scenarios_path)
        return p if p.is_absolute() else REPO_ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

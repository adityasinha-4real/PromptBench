"""Application configuration.

All secrets are read from the environment (or a local ``.env`` file) and are
never persisted to the database or returned to the frontend.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Runtime settings, populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Application -------------------------------------------------
    app_name: str = "PromptBench"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    api_prefix: str = "/api"

    # ---- Database ----------------------------------------------------
    # SQLite by default; swap in ``postgresql+asyncpg://...`` for Postgres.
    database_url: str = Field(default=f"sqlite+aiosqlite:///{BACKEND_ROOT / 'promptbench.db'}")

    # ---- CORS ---------------------------------------------------------
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    # ---- Provider credentials (never leave the backend) ---------------
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ollama_base_url: str = "http://localhost:11434"

    # ---- Execution limits --------------------------------------------
    request_timeout_seconds: float = Field(default=120.0, ge=1.0, le=900.0)
    connect_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0.0, le=10.0)
    max_concurrency: int = Field(default=8, ge=1, le=64)

    # ---- Input validation limits --------------------------------------
    max_prompt_chars: int = Field(default=32_000, ge=100, le=1_000_000)
    max_system_prompt_chars: int = Field(default=8_000, ge=0, le=200_000)
    max_output_tokens_limit: int = Field(default=8_192, ge=1, le=200_000)
    max_models_per_benchmark: int = Field(default=12, ge=1, le=64)
    max_variants_per_benchmark: int = Field(default=10, ge=1, le=64)

    # ---- Evaluation ----------------------------------------------------
    evaluation_default_mode: str = Field(default="heuristic")
    judge_provider: str | None = None
    judge_model: str | None = None

    # ---- Pricing --------------------------------------------------------
    pricing_file: str | None = None

    @field_validator("environment")
    @classmethod
    def _normalise_env(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "prod"}

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return origins or ["http://localhost:3000"]

    @property
    def pricing_path(self) -> Path:
        if self.pricing_file:
            return Path(self.pricing_file)
        return BACKEND_ROOT / "app" / "core" / "pricing.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


settings = get_settings()

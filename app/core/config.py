"""Application settings via pydantic-settings.

Single source of truth for env-driven configuration. All other modules read
from `settings` here — never from `os.environ` directly.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Strongly-typed settings loaded from env / .env.

    Validators keep dev ergonomics forgiving (missing OpenAI key warns instead
    of crashing) while required infra (POSTGRES_DB) stays enforced.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # ── App ──
    app_env: str = Field(default="development", description="deployment environment")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_log_level: str = Field(default="INFO")

    # ── Postgres ──
    postgres_user: str = Field(default="vivi")
    postgres_password: str = Field(default="vivi")
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="vivi")

    # ── OpenAI ──
    openai_api_key: str = Field(default="", description="May be empty in dev (LLM disabled).")
    openai_model: str = Field(default="gpt-5-mini")
    openai_temperature: float = Field(default=0.3)

    # ── Agent runtime ──
    llm_checkpointer: str = Field(default="memory", description="memory | postgres")
    agent_max_turns: int = Field(default=10)
    agent_timeout_seconds: int = Field(default=60)
    agent_history_limit: int = Field(default=20)
    agent_max_tool_result_chars: int = Field(default=8000)

    # ── WhatsApp ──
    whatsapp_webhook_verify_token: str = Field(default="", description="Token echoed to Meta during the webhook GET handshake.")
    whatsapp_api_token: str = Field(default="", description="System user access token for outbound messages via Graph API.")
    whatsapp_phone_number_id: str = Field(default="", description="Phone number id from the Meta dashboard, used in the Graph API URL.")
    whatsapp_api_version: str = Field(default="v25.0", description="Meta Graph API version (e.g. v25.0).")

    @field_validator("postgres_db")
    @classmethod
    def _postgres_db_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("POSTGRES_DB is required and must be non-empty")
        return v.strip()

    @field_validator("openai_api_key")
    @classmethod
    def _warn_empty_openai_key(cls, v: str) -> str:
        if not v:
            logger.warning(
                "OPENAI_API_KEY is empty — LLM features will be disabled. "
                "Set OPENAI_API_KEY in .env to enable the agent."
            )
        return v

    @field_validator("whatsapp_api_token")
    @classmethod
    def _warn_empty_whatsapp(cls, v: str) -> str:
        if not v:
            logger.warning(
                "WHATSAPP_API_TOKEN is empty — WhatsApp channel will be disabled. "
                "Set WHATSAPP_API_TOKEN in .env to enable inbound/outbound messages."
            )
        return v

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN (psycopg driver)."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def pg_async_dsn(self) -> str:
        """Plain psycopg3 async DSN for the LangGraph checkpointer."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_test_env(self) -> bool:
        return self.app_env.lower() in {"test", "testing"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
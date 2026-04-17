from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    # LLM provider keys
    ANTHROPIC_API_KEY: SecretStr | None = None
    OPENAI_API_KEY: SecretStr | None = None

    # Integrations
    SLACK_BOT_TOKEN: SecretStr | None = None
    SLACK_APP_TOKEN: SecretStr | None = None
    SLACK_CHANNEL_ID: str | None = None
    LANGFUSE_SECRET_KEY: SecretStr | None = None
    DATADOG_WEBHOOK_TOKEN: SecretStr | None = None

    # Infrastructure
    REDIS_URL: str = "redis://localhost:6379/0"
    DATABASE_URL: str = "postgresql://incident-agent@localhost:5432/incident-agent"

    # Agent behavior
    REQUIRE_APPROVAL: bool = False

    # Hosted demo configuration
    DEMO_HOSTING_TARGET: str = "render"
    DEMO_ENVIRONMENT: str = "demo"
    DEMO_BASE_URL: str = "http://localhost:8002"
    GATEWAY_BASE_URL: str = "http://localhost:8000"
    DEMO_TRIGGER_TOKEN: SecretStr | None = None
    APPROVAL_SIGNING_SECRET: SecretStr | None = None


settings = Settings()


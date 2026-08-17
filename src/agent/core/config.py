"""Application configuration using Pydantic Settings.

Single source of truth for all configuration values. Loaded from environment
variables and .env files. Nested models provide structured access to related
settings (LLM, ServiceNow, Browser, Agent).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LLM_",
        extra="ignore",
    )

    provider: Literal["openai", "groq", "anthropic", "nvidia"] = "openai"
    api_key: str = Field(
        default="", validation_alias="OPENAI_API_KEY", description="API key for the LLM provider"
    )
    base_url: str | None = Field(default=None, description="Base URL for the LLM API endpoint")
    model: str = Field(default="gpt-4o", description="Model identifier")
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Embedding model identifier"
    )
    embedding_dimensions: int = Field(
        default=1536, description="Embedding vector dimensions (must match embedding model output)"
    )
    max_tokens: int = Field(default=4096, description="Max tokens per response")
    temperature: float = Field(default=0.1, description="Sampling temperature")
    max_retries: int = Field(default=2, description="Max retries for LLM requests")


class ServiceNowConfig(BaseSettings):
    """ServiceNow instance configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SERVICENOW_",
        extra="ignore",
    )

    instance_url: str = Field(
        default="https://dev12345.service-now.com",
        description="ServiceNow instance base URL",
    )
    username: str = Field(default="admin", description="Login username")
    password: str = Field(default="", description="Login password")


class BrowserConfig(BaseSettings):
    """Playwright browser configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BROWSER_",
        extra="ignore",
    )

    headless: bool = Field(default=True, description="Run in headless mode")
    slow_mo: int = Field(default=0, description="Slow down actions by N ms")
    timeout: int = Field(default=30000, description="Default timeout in ms")
    viewport_width: int = Field(default=1920, description="Viewport width")
    viewport_height: int = Field(default=1080, description="Viewport height")


class SessionConfig(BaseSettings):
    """Session storage configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SESSION_",
        extra="ignore",
    )

    store_type: Literal["memory", "redis"] = Field(
        default="memory", description="Backend to use ('memory' or 'redis')"
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
        description="Redis connection URL",
    )
    redis_prefix: str = Field(default="session:", description="Redis key prefix")


class PerceptionConfig(BaseSettings):
    """Perception Layer configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PERCEPTION_",
        extra="ignore",
    )

    puter_endpoint: str | None = Field(
        default=None,
        validation_alias="PUTER_ENDPOINT",
        description="URL for Puter's hosted UI-TARS API",
    )
    puter_api_key: str | None = Field(
        default=None, validation_alias="PUTER_API_KEY", description="API key for Puter"
    )
    moondream_api_key: str | None = Field(
        default=None, validation_alias="MOONDREAM_API_KEY", description="API key for Moondream"
    )
    gemini_api_key: str | None = Field(
        default=None, validation_alias="GEMINI_API_KEY", description="API key for Gemini"
    )
    grounding_threshold: float = Field(
        default=0.8, description="Minimum confidence threshold for grounding"
    )
    recovery_store_type: Literal["memory", "redis"] = Field(
        default="memory", description="Backend for recovery store"
    )


class AgentConfig(BaseSettings):
    """Agent runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENT_",
        extra="ignore",
    )

    max_steps: int = Field(default=100, description="Max steps before forced stop")
    max_retries: int = Field(default=3, description="Max recovery retries per action")
    observation_window: int = Field(
        default=10, description="Number of observations to keep in memory"
    )


class DomainConfig(BaseSettings):
    """Domain Intelligence Layer configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DOMAIN_",
        extra="ignore",
    )

    postgres_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/servicenow_qa",
        validation_alias="DATABASE_URL",
        description="Postgres connection string (with pgvector support)",
    )
    drift_polling_interval: int = Field(
        default=300, description="Interval in seconds to poll for metadata drift"
    )

    @property
    def asyncpg_dsn(self) -> str:
        """Convert SQLAlchemy async DSN to native asyncpg-compatible DSN."""
        url = self.postgres_url
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql://", 1)
        if url.startswith("postgres+asyncpg://"):
            return url.replace("postgres+asyncpg://", "postgres://", 1)
        return url


class Settings(BaseSettings):
    """Root application settings.

    Aggregates all sub-configurations and provides global settings
    for logging, reporting, and output directories.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Sub-configurations
    llm: LLMConfig = Field(default_factory=LLMConfig)
    servicenow: ServiceNowConfig = Field(default_factory=ServiceNowConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")

    # Auth
    jwt_secret_key: str = Field(
        default="super-secret-local-development-key", validation_alias="JWT_SECRET_KEY"
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")

    # Output directories
    report_output_dir: Path = Field(default=Path("reports"))
    screenshot_dir: Path = Field(default=Path("screenshots"))

    def ensure_directories(self) -> None:
        """Create output directories if they don't exist."""
        self.report_output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Factory function for Settings. Used as a FastAPI dependency."""
    return Settings()

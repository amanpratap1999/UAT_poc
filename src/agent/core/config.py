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

    provider: Literal["openai", "groq", "anthropic"] = "openai"
    api_key: str = Field(default="", description="API key for the LLM provider")
    model: str = Field(default="gpt-4o", description="Model identifier")
    max_tokens: int = Field(default=4096, description="Max tokens per response")
    temperature: float = Field(default=0.1, description="Sampling temperature")


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

    headless: bool = Field(default=False, description="Run in headless mode")
    slow_mo: int = Field(default=0, description="Slow down actions by N ms")
    timeout: int = Field(default=30000, description="Default timeout in ms")
    viewport_width: int = Field(default=1920, description="Viewport width")
    viewport_height: int = Field(default=1080, description="Viewport height")


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

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"

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

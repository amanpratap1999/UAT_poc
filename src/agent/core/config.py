"""Application configuration using Pydantic Settings.

Single source of truth for all configuration values. Loaded from environment
variables and .env files. Nested models provide structured access to related
settings (LLM, ServiceNow, Browser, Agent).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_active_env_file() -> Path | None:
    """Determine active .env file based on environment variables and runtime mode.

    Precedence:
    1. Explicit UAT_ENV_FILE from process environment.
    2. UAT_RUNTIME_MODE=local -> .env.local (if exists).
    3. UAT_RUNTIME_MODE=docker or /.dockerenv -> .env.docker (if exists; never loads .env.local).
    4. Local host execution fallback -> .env.local if exists, else .env.
    5. Fallback -> .env if exists.
    """
    custom = os.environ.get("UAT_ENV_FILE")
    if custom:
        p = Path(custom)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        return p if p.is_file() else Path(custom)

    mode = os.environ.get("UAT_RUNTIME_MODE", "").strip().lower()
    in_docker = mode == "docker" or os.path.exists("/.dockerenv")

    if mode == "local":
        local_p = REPO_ROOT / ".env.local"
        if local_p.is_file():
            return local_p

    if in_docker:
        docker_p = REPO_ROOT / ".env.docker"
        if docker_p.is_file():
            return docker_p
        return None

    # Host execution: check .env.local first
    local_p = REPO_ROOT / ".env.local"
    if local_p.is_file():
        return local_p

    default_p = REPO_ROOT / ".env"
    if default_p.is_file():
        return default_p

    return None


def load_active_env() -> Path | None:
    """Load active env file into os.environ with override=False (process env takes precedence)."""
    active = get_active_env_file()
    if active and active.is_file():
        load_dotenv(dotenv_path=active, override=False)
    return active


# Initial bootstrap load
load_active_env()


class BaseSubConfig(BaseSettings):
    """Base sub-configuration that binds to the dynamically resolved active env file."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        active = get_active_env_file()
        if "_env_file" not in kwargs and active is not None:
            kwargs["_env_file"] = active
        super().__init__(*args, **kwargs)


class LLMConfig(BaseSubConfig):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(
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
        default="nvidia/nemotron-3-embed-1b", description="Embedding model identifier"
    )
    embedding_base_url: str | None = Field(
        default=None, description="Optional override for embeddings base URL"
    )
    embedding_api_key: str | None = Field(
        default=None, description="Optional override for embeddings API key"
    )
    embedding_dimensions: int = Field(
        default=2048, description="Embedding vector dimensions (must match embedding model output)"
    )
    embedding_startup_health_check: bool = Field(
        default=True, description="Validate embedding model availability on startup"
    )
    max_tokens: int = Field(default=4096, description="Max tokens per response")
    temperature: float = Field(default=0.1, description="Sampling temperature")
    max_retries: int = Field(default=2, description="Max retries for LLM requests")


class ServiceNowConfig(BaseSubConfig):
    """ServiceNow instance configuration."""

    model_config = SettingsConfigDict(
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

    # P1.9 Role/Persona Execution
    personas: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Dictionary mapping persona names to credentials (e.g. {'itil_user': {'username': 'u1', 'password': 'p1'}})"
    )
    active_persona: str | None = Field(
        default=None, 
        description="The currently active persona name, if any"
    )

    def get_active_credentials(self) -> tuple[str, str]:
        """Get credentials for the active persona, falling back to defaults."""
        if self.active_persona and self.personas and self.active_persona in self.personas:
            p = self.personas[self.active_persona]
            return p.get("username", self.username), p.get("password", self.password)
        return self.username, self.password


class BrowserConfig(BaseSubConfig):
    """Playwright browser configuration."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_prefix="BROWSER_",
        extra="ignore",
    )

    headless: bool = Field(
        default=False,
        validation_alias=AliasChoices("BROWSER_HEADLESS", "headless"),
        description="Run in headless mode",
    )
    slow_mo: int = Field(
        default=0,
        validation_alias=AliasChoices("BROWSER_SLOW_MO", "slow_mo"),
        description="Slow down actions by N ms",
    )
    show_mouse_cursor: bool = Field(
        default=True,
        validation_alias=AliasChoices("BROWSER_SHOW_MOUSE_CURSOR", "show_mouse_cursor"),
        description="Show visual cursor indicator in browser",
    )
    keep_browser_open: bool = Field(
        default=False,
        validation_alias=AliasChoices("BROWSER_KEEP_BROWSER_OPEN", "keep_browser_open"),
        description="Keep browser open after run completes",
    )
    interactive_timeout_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices(
            "BROWSER_INTERACTIVE_TIMEOUT_SECONDS", "interactive_timeout_seconds"
        ),
        description="Max seconds to keep headed browser open after run when unattended",
    )
    timeout: int = Field(
        default=240000,
        validation_alias=AliasChoices("BROWSER_TIMEOUT", "timeout"),
        description="Default Playwright timeout in ms (covers navigation + element waits)",
    )
    viewport_width: int = Field(default=1920, description="Viewport width")
    viewport_height: int = Field(default=1080, description="Viewport height")
    record_browser: bool = Field(default=False, description="Record browser sessions as video")
    user_data_dir: str | None = Field(
        default=None, description="Path to isolated browser profile directory"
    )


class SessionConfig(BaseSubConfig):
    """Session storage configuration."""

    model_config = SettingsConfigDict(
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
    celery_broker_url: str = Field(
        default="",
        validation_alias="CELERY_BROKER_URL",
        description="Celery broker URL",
    )
    celery_result_backend: str = Field(
        default="",
        validation_alias="CELERY_RESULT_BACKEND",
        description="Celery result backend URL",
    )


class PerceptionConfig(BaseSubConfig):
    """Perception Layer configuration."""

    model_config = SettingsConfigDict(
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
    confidence_high: float = Field(
        default=0.85, description="High confidence threshold for direct execution"
    )
    confidence_medium: float = Field(
        default=0.60, description="Medium confidence threshold for Gemini verification"
    )
    recovery_store_type: Literal["memory", "redis"] = Field(
        default="memory", description="Backend for recovery store"
    )


class SecurityConfig(BaseSubConfig):
    """Browser action security and allowlist policy configuration."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_prefix="SECURITY_",
        extra="ignore",
    )

    allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "service-now.com",
            "localhost",
            "127.0.0.1",
        ],
        description="Allowed domains/hosts for browser navigation",
    )
    blocked_actions: list[str] = Field(
        default_factory=list,
        description="List of forbidden action types",
    )
    allow_js_evaluation: bool = Field(
        default=False,
        description="Whether to permit arbitrary JS script evaluation",
    )


class AgentConfig(BaseSubConfig):
    """Agent runtime configuration."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_prefix="AGENT_",
        extra="ignore",
    )

    max_steps: int = Field(default=100, description="Max steps before forced stop")
    max_retries: int = Field(default=3, description="Max recovery retries per action")
    max_recovery_depth: int = Field(
        default=3,
        description="Max recovery cycles allowed for the same action before terminal failure",
    )
    max_backoff_delay: float = Field(
        default=10.0,
        description="Upper bound (seconds) for exponential recovery backoff",
    )
    observation_window: int = Field(
        default=10, description="Number of observations to keep in memory"
    )
    execution_mode: Literal["fast", "balanced", "thorough"] = Field(
        default="balanced",
        description="Execution mode: fast (DOM-first, minimal LLM), balanced, or thorough",
    )
    step_cache_path: str = Field(
        default="step_cache.db",
        description=(
            "Path to the step resolution/parsing cache DB. Configurable via "
            "AGENT_STEP_CACHE_PATH. Must point at a shared persistent volume "
            "when API and worker run in separate containers."
        ),
    )
    require_approval_risk_threshold: int = Field(
        default=8, description="Risk level (1-10) requiring human approval before execution"
    )


class DomainConfig(BaseSubConfig):
    """Domain Intelligence Layer configuration."""

    model_config = SettingsConfigDict(
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


class Settings(BaseSubConfig):
    """Root application settings.

    Aggregates all sub-configurations and provides global settings
    for logging, reporting, and output directories.
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Runtime mode
    runtime_mode: Literal["local", "docker"] = Field(
        default="local",
        validation_alias=AliasChoices("UAT_RUNTIME_MODE", "runtime_mode"),
        description="Application runtime mode: 'local' (host machine) or 'docker' (container)",
    )

    # Sub-configurations
    llm: LLMConfig = Field(default_factory=LLMConfig)
    servicenow: ServiceNowConfig = Field(default_factory=ServiceNowConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

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
    report_output_dir: Path = Field(
        default=Path("reports"),
        validation_alias=AliasChoices("REPORT_OUTPUT_DIR", "report_output_dir"),
    )
    screenshot_dir: Path = Field(
        default=Path("screenshots"),
        validation_alias=AliasChoices("SCREENSHOT_DIR", "screenshot_dir"),
    )

    @field_validator("report_output_dir", "screenshot_dir", mode="after")
    @classmethod
    def _resolve_dir_path(cls, v: Path) -> Path:
        """Resolve relative paths against repository root rather than cwd."""
        v_str = str(v).replace("\\", "/")
        if v_str.startswith("/"):
            return Path(v_str)
        if not v.is_absolute():
            return (REPO_ROOT / v).resolve()
        return v

    @model_validator(mode="after")
    def _validate_jwt_secret_for_runtime(self) -> "Settings":
        """Fail fast on insecure JWT secrets outside local development.

        Security invariant (P0): a production/container runtime must never start
        with the well-known development fallback secret, an empty secret, or a
        trivially short secret — any of those would let an attacker forge
        auth tokens. Local development on a developer machine may retain the
        explicit development fallback so `scripts/start-local.ps1` keeps working.
        """
        secret = (self.jwt_secret_key or "").strip()
        fallback = "super-secret-local-development-key"

        is_local = self.runtime_mode == "local" and self.environment in (
            "development", "dev", "local",
        )

        if is_local:
            # Local development: permitted, but loudly warn on the fallback.
            if secret == fallback:
                import warnings

                warnings.warn(
                    "JWT_SECRET_KEY not set — using the development fallback secret. "
                    "This is only acceptable for local development; set JWT_SECRET_KEY "
                    "explicitly for docker/production deployments.",
                    stacklevel=2,
                )
            return self

        if not secret or secret == fallback or len(secret) < 32:
            raise ValueError(
                "Refusing to start: JWT_SECRET_KEY must be set to a strong secret "
                "(>= 32 chars) when UAT_RUNTIME_MODE != 'local' or ENVIRONMENT is "
                "not development. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return self

    def ensure_directories(self) -> None:
        """Create output directories if they don't exist."""
        self.report_output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def safe_dict(self) -> dict[str, Any]:
        """Return a sanitized dictionary of settings safe for logging and diagnostics."""

        def _mask_url_password(url: str) -> str:
            return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)

        return {
            "runtime_mode": self.runtime_mode,
            "environment": self.environment,
            "log_level": self.log_level,
            "active_env_file": str(get_active_env_file() or ""),
            "repo_root": str(REPO_ROOT),
            "report_output_dir": str(self.report_output_dir),
            "screenshot_dir": str(self.screenshot_dir),
            "database_url": _mask_url_password(self.domain.postgres_url),
            "redis_url": _mask_url_password(self.session.redis_url),
            "celery_broker_url": _mask_url_password(
                self.session.celery_broker_url or self.session.redis_url
            ),
            "celery_result_backend": _mask_url_password(
                self.session.celery_result_backend or self.session.redis_url
            ),
            "browser": {
                "headless": self.browser.headless,
                "slow_mo": self.browser.slow_mo,
                "show_mouse_cursor": self.browser.show_mouse_cursor,
                "keep_browser_open": self.browser.keep_browser_open,
                "interactive_timeout_seconds": self.browser.interactive_timeout_seconds,
            },
            "servicenow": {
                "instance_url": self.servicenow.instance_url,
                "username": self.servicenow.username,
                "password_configured": bool(self.servicenow.password),
            },
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "base_url": self.llm.base_url,
                "embedding_model": self.llm.embedding_model,
                "embedding_dimensions": self.llm.embedding_dimensions,
                "api_key_configured": bool(self.llm.api_key),
            },
            "auth": {
                "jwt_algorithm": self.jwt_algorithm,
                "jwt_secret_configured": bool(self.jwt_secret_key),
            },
            "agent": {
                "step_cache_path": self.agent.step_cache_path,
                "max_recovery_depth": self.agent.max_recovery_depth,
                "max_backoff_delay": self.agent.max_backoff_delay,
            },
        }


def get_settings() -> Settings:
    """Factory function for Settings. Used as a FastAPI dependency."""
    return Settings()


def resolve_step_cache_path() -> Path:
    """Resolve the step-cache DB path against the repository root.

    The configured value (``AGENT_STEP_CACHE_PATH``) may be relative; such
    paths are anchored to ``REPO_ROOT`` so the API and Celery worker agree on
    one location regardless of their working directory. Absolute paths (the
    recommended form for Docker, e.g. ``/app/cache/step_cache.db``) are used
    verbatim.
    """
    raw = get_settings().agent.step_cache_path
    p = Path(raw)
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()



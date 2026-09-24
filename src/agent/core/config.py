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
        default="",
        description="ServiceNow instance base URL",
    )
    is_subproduction: bool = Field(
        default=False,
        description="Explicitly declare this instance as sub-production. Production instances cannot be mutated.",
    )
    username: str = Field(default="", description="Login username")
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
    allow_mutations: bool = Field(
        default=False, 
        description="Allow tests to modify state (must be explicit to touch prod)."
    )
    allowed_instances: list[str] = Field(
        default_factory=list,
        description="Whitelist of instance hostnames allowed to be mutated."
    )
    api_oracle_enabled: bool = Field(
        default=True,
        description=(
            "Query the Table API as an independent persistence oracle after "
            "mutations (QA-005). Disable only when the credentials intentionally "
            "have no REST API access; persistence is then reported as "
            "'disabled' instead of 'verified'."
        ),
    )

    def get_active_credentials(self) -> tuple[str, str]:
        """Get credentials for the active persona.

        INC-UAT-05 (Blocker): Previously fell back to default username/password
        when an unknown persona was requested — a typo could silently execute
        as the wrong user (administrator). Now: if active_persona is set but
        not found in the personas dict, raise ValueError. No silent fallback.
        """
        if not self.active_persona:
            return self.username, self.password
        if self.active_persona not in self.personas:
            raise ValueError(
                f"Unknown persona '{self.active_persona}' — no credentials "
                f"configured. Set SERVICENOW_PERSONAS to include this persona, "
                f"or clear SERVICENOW_ACTIVE_PERSONA to use default credentials. "
                f"INC-UAT-05: no silent fallback to prevent wrong-user execution."
            )
        p = self.personas[self.active_persona]
        return p.get("username", self.username), p.get("password", self.password)


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
        default="memory",
        validation_alias=AliasChoices("SESSION_STORE_TYPE", "store_type"),
        description="Backend to use ('memory' or 'redis')",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
        description="Redis connection URL",
    )
    redis_prefix: str = Field(default="session:", description="Redis key prefix")
    redis_tls_ca_cert: str = Field(
        default="",
        validation_alias=AliasChoices("REDIS_TLS_CA_CERT", "redis_tls_ca_cert"),
        description="Path to Redis TLS CA cert file",
    )
    redis_tls_cert: str = Field(
        default="",
        validation_alias=AliasChoices("REDIS_TLS_CERT", "redis_tls_cert"),
        description="Path to Redis TLS client certificate file",
    )
    redis_tls_key: str = Field(
        default="",
        validation_alias=AliasChoices("REDIS_TLS_KEY", "redis_tls_key"),
        description="Path to Redis TLS client key file",
    )
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


class SafetyBudgetConfig(BaseSubConfig):
    """Execution safety budgets for QA engine runs (QA-016)."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_prefix="SAFETY_BUDGET_",
        extra="ignore",
    )

    max_actions_per_run: int = Field(
        default=50,
        validation_alias=AliasChoices("SAFETY_BUDGET_MAX_ACTIONS", "max_actions_per_run"),
        description="Max total browser/agent actions per run",
    )
    max_mutations_per_run: int = Field(
        default=20,
        validation_alias=AliasChoices("SAFETY_BUDGET_MAX_MUTATIONS", "max_mutations_per_run"),
        description="Max mutating actions (fill/select/submit) per run",
    )
    max_records_per_run: int = Field(
        default=10,
        validation_alias=AliasChoices("SAFETY_BUDGET_MAX_RECORDS", "max_records_per_run"),
        description="Max distinct records allowed to be touched per run",
    )
    max_tables_per_run: int = Field(
        default=5,
        validation_alias=AliasChoices("SAFETY_BUDGET_MAX_TABLES", "max_tables_per_run"),
        description="Max distinct tables allowed to be touched per run",
    )
    max_destructive_operations: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "SAFETY_BUDGET_MAX_DESTRUCTIVE", "max_destructive_operations"
        ),
        description="Max destructive actions (delete, drop, truncate) per run",
    )
    max_run_time_seconds: float = Field(
        default=1800.0,
        validation_alias=AliasChoices(
            "SAFETY_BUDGET_MAX_RUN_TIME_SECONDS", "max_run_time_seconds"
        ),
        description="Max total wall-clock runtime in seconds before forced abort",
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
    safety_budgets: SafetyBudgetConfig = Field(default_factory=SafetyBudgetConfig)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")

    # Auth
    jwt_secret_key: str = Field(
        default="super-secret-local-development-key", validation_alias="JWT_SECRET_KEY"
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    # Audit issue I1 (P1): previously auth.py read this via `_settings.__dict__.get(...)`
    # which always returned 60 because Pydantic does not populate __dict__ for
    # BaseSettings. Declaring it as a real field makes the env var work.
    access_token_expire_minutes: int = Field(
        default=60, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES",
        description="Lifetime (minutes) of issued JWT access tokens.",
    )

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
    def _validate_instance_url(self) -> "Settings":
        if self.servicenow.instance_url == "https://dev12345.service-now.com" or not self.servicenow.instance_url:
            raise ValueError("SERVICENOW_INSTANCE_URL is not set or is using the default placeholder. Execution cannot proceed.")
        return self

    @model_validator(mode="after")
    def _validate_servicenow_credentials(self) -> "Settings":
        """Require explicit ServiceNow credentials outside local development."""
        is_local = self.runtime_mode == "local" and self.environment in (
            "development", "dev", "local",
        )
        if not is_local:
            username = (self.servicenow.username or "").strip()
            password = self.servicenow.password or ""
            if not username or not password:
                raise ValueError(
                    "Refusing to start: SERVICENOW_USERNAME and SERVICENOW_PASSWORD "
                    "must be configured outside local development."
                )
        return self

    @model_validator(mode="after")
    def _validate_jwt_secret_for_runtime(self) -> "Settings":
        """Fail fast on insecure JWT secrets outside local development.

        Security invariant (P0): a production/container runtime must never start
        with the well-known development fallback secret, an empty secret, a
        trivially short secret, or a placeholder/example secret copied verbatim
        from the project's own .env.docker.example. Any of those would let an
        attacker forge auth tokens. Local development on a developer machine
        may retain the explicit development fallback so
        `scripts/start-local.ps1` keeps working.
        """
        import math
        import warnings

        secret = (self.jwt_secret_key or "").strip()
        fallback = "super-secret-local-development-key"

        # Blocklist of placeholder/example secrets that ship in this repo's
        # .env.docker.example and similar documentation. Operators who copy
        # these verbatim into .env.docker would pass the legacy length check
        # while running with a publicly-known secret (audit issue I5).
        _PLACEHOLDER_BLOCKLIST = frozenset({
            "CHANGE_THIS_TO_A_SECURE_SECRET_AT_LEAST_32_CHARS",
            "REPLACE_ME_WITH_A_SECURE_SECRET_AT_LEAST_32_CHARS",
            "REPLACE_ME_RUN_python_secrets_token_urlsafe_48",
            "GENERATE_A_LONG_RANDOM_SECRET",
            "GENERATE_A_SECURE_SECRET_HERE",
            "PLEASE_REPLACE_THIS_WITH_A_REAL_SECRET",
            fallback,
        })

        def _shannon_entropy(s: str) -> float:
            """Bits-per-char Shannon entropy. Used to reject low-entropy secrets."""
            if not s:
                return 0.0
            counts: dict[str, int] = {}
            for ch in s:
                counts[ch] = counts.get(ch, 0) + 1
            n = len(s)
            return -sum((c / n) * math.log2(c / n) for c in counts.values())

        is_local = self.runtime_mode == "local" and self.environment in (
            "development", "dev", "local",
        )

        if is_local:
            # Local development: permitted, but loudly warn on the fallback.
            if secret == fallback:
                warnings.warn(
                    "JWT_SECRET_KEY not set — using the development fallback secret. "
                    "This is only acceptable for local development; set JWT_SECRET_KEY "
                    "explicitly for docker/production deployments.",
                    stacklevel=2,
                )
            return self

        # Production / non-local: reject empty, short, blocklisted, or low-entropy.
        if not secret or secret == fallback or len(secret) < 32:
            raise ValueError(
                "Refusing to start: JWT_SECRET_KEY must be set to a strong secret "
                "(>= 32 chars) when UAT_RUNTIME_MODE != 'local' or ENVIRONMENT is "
                "not development. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if secret in _PLACEHOLDER_BLOCKLIST:
            raise ValueError(
                "Refusing to start: JWT_SECRET_KEY matches a known placeholder/"
                "example secret shipped in this repo's .env.docker.example. "
                "Generate a fresh secret with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        # Reject low-entropy secrets (e.g. repetitive strings, digits-only)
        # that pass the length/blocklist checks but are still trivially guessable.
        entropy = _shannon_entropy(secret)
        if entropy < 2.5:
            raise ValueError(
                f"Refusing to start: JWT_SECRET_KEY has low Shannon entropy "
                f"({entropy:.2f} bits/char, minimum 2.5). Use a uniformly random "
                f"secret, not a structured or repetitive string."
            )
        return self

    @model_validator(mode="after")
    def _validate_redis_tls_certs(self) -> "Settings":
        """Fail startup clearly if Redis TLS is configured but certificates do not exist."""
        for name, path_str in [
            ("REDIS_TLS_CA_CERT", self.session.redis_tls_ca_cert),
            ("REDIS_TLS_CERT", self.session.redis_tls_cert),
            ("REDIS_TLS_KEY", self.session.redis_tls_key),
        ]:
            if path_str and not Path(path_str).exists():
                raise ValueError(
                    f"Refusing to start: {name} is configured ({path_str}) but file does not exist."
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



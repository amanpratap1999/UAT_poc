"""Unit tests for Local and Docker runtime modes, environment loading, and path resolution."""

import os
from pathlib import Path

import pytest

from agent.core.config import (
    REPO_ROOT,
    BrowserConfig,
    DomainConfig,
    SessionConfig,
    Settings,
    get_active_env_file,
)


def test_local_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify local runtime mode defaults."""
    monkeypatch.setenv("UAT_RUNTIME_MODE", "local")
    monkeypatch.delenv("UAT_ENV_FILE", raising=False)
    monkeypatch.delenv("REPORT_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("SCREENSHOT_DIR", raising=False)

    s = Settings()
    assert s.runtime_mode == "local"
    # Relative dirs resolve to REPO_ROOT
    assert s.report_output_dir == (REPO_ROOT / "reports").resolve()
    assert s.screenshot_dir == (REPO_ROOT / "screenshots").resolve()
    # Masked safe dictionary
    safe = s.safe_dict()
    assert safe["runtime_mode"] == "local"
    assert safe["report_output_dir"] == str(s.report_output_dir)
    assert safe["screenshot_dir"] == str(s.screenshot_dir)
    assert "***" in safe["database_url"]


def test_docker_settings_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify docker runtime mode defaults and path preservation."""
    monkeypatch.setenv("UAT_RUNTIME_MODE", "docker")
    monkeypatch.setenv("REPORT_OUTPUT_DIR", "/app/reports")
    monkeypatch.setenv("SCREENSHOT_DIR", "/app/screenshots")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:secret@db:5432/servicenow_qa")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("BROWSER_HEADLESS", "true")

    s = Settings()
    assert s.runtime_mode == "docker"
    # Absolute paths are preserved
    assert str(s.report_output_dir).replace("\\", "/") == "/app/reports"
    assert str(s.screenshot_dir).replace("\\", "/") == "/app/screenshots"
    assert s.browser.headless is True
    assert "db:5432" in s.domain.postgres_url
    assert "redis:6379" in s.session.redis_url

    safe = s.safe_dict()
    assert safe["runtime_mode"] == "docker"
    assert "secret" not in safe["database_url"]
    assert "***" in safe["database_url"]


def test_environment_precedence_over_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify environment variables already exported in process take precedence over .env files."""
    dummy_env = tmp_path / ".env.test_precedence"
    dummy_env.write_text(
        "DATABASE_URL=postgresql+asyncpg://file_user:file_pass@file_host:5432/file_db\n"
        "BROWSER_HEADLESS=false\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("UAT_ENV_FILE", str(dummy_env))
    # Exported in process environment -> MUST WIN
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://env_user:env_pass@env_host:5432/env_db")

    s = Settings()
    assert "env_host" in s.domain.postgres_url
    assert "file_host" not in s.domain.postgres_url


def test_active_env_file_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_active_env_file resolves correctly under different modes."""
    # 1. Custom UAT_ENV_FILE
    custom_file = tmp_path / ".env.custom"
    custom_file.write_text("TEST=1", encoding="utf-8")
    monkeypatch.setenv("UAT_ENV_FILE", str(custom_file))
    assert get_active_env_file() == custom_file

    # 2. Local mode with existing .env.local
    monkeypatch.delenv("UAT_ENV_FILE")
    monkeypatch.setenv("UAT_RUNTIME_MODE", "local")
    env_local = REPO_ROOT / ".env.local"
    if env_local.is_file():
        assert get_active_env_file() == env_local


def test_headed_browser_local_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify headed browser execution configuration for local mode."""
    monkeypatch.setenv("BROWSER_HEADLESS", "false")
    monkeypatch.setenv("BROWSER_SLOW_MO", "250")
    monkeypatch.setenv("BROWSER_SHOW_MOUSE_CURSOR", "true")
    monkeypatch.setenv("BROWSER_KEEP_BROWSER_OPEN", "true")
    monkeypatch.setenv("BROWSER_INTERACTIVE_TIMEOUT_SECONDS", "300")

    cfg = BrowserConfig()
    assert cfg.headless is False
    assert cfg.slow_mo == 250
    assert cfg.show_mouse_cursor is True
    assert cfg.keep_browser_open is True
    assert cfg.interactive_timeout_seconds == 300


def test_celery_broker_and_result_backend_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Celery broker and result backend URLs resolve with fallback to Redis."""
    # 1. Explicit Celery URLs
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")

    session_cfg = SessionConfig()
    assert session_cfg.celery_broker_url == "redis://127.0.0.1:6379/0"
    assert session_cfg.celery_result_backend == "redis://127.0.0.1:6379/1"

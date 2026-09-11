"""Unit tests for configuration and DSN conversions."""

from agent.core.config import BrowserConfig, DomainConfig


def test_domain_config_asyncpg_dsn_conversion() -> None:
    """Test that DomainConfig.asyncpg_dsn converts SQLAlchemy DSNs to native asyncpg DSNs."""
    # 1. postgresql+asyncpg:// -> postgresql://
    cfg1 = DomainConfig.model_construct(
        postgres_url="postgresql+asyncpg://user:pass@db:5432/mydb"
    )
    assert cfg1.asyncpg_dsn == "postgresql://user:pass@db:5432/mydb"
    assert cfg1.postgres_url == "postgresql+asyncpg://user:pass@db:5432/mydb"

    # 2. postgres+asyncpg:// -> postgres://
    cfg2 = DomainConfig.model_construct(
        postgres_url="postgres+asyncpg://user:pass@localhost:5432/mydb"
    )
    assert cfg2.asyncpg_dsn == "postgres://user:pass@localhost:5432/mydb"

    # 3. postgresql:// unchanged
    cfg3 = DomainConfig.model_construct(
        postgres_url="postgresql://user:pass@db:5432/mydb"
    )
    assert cfg3.asyncpg_dsn == "postgresql://user:pass@db:5432/mydb"

    # 4. postgres:// unchanged
    cfg4 = DomainConfig.model_construct(
        postgres_url="postgres://user:pass@db:5432/mydb"
    )
    assert cfg4.asyncpg_dsn == "postgres://user:pass@db:5432/mydb"

    # 5. Empty string
    cfg5 = DomainConfig.model_construct(postgres_url="")
    assert cfg5.asyncpg_dsn == ""


def test_browser_config_defaults() -> None:
    """Verify BrowserConfig defaults to headed mode (headless=False) with cursor indicator."""
    cfg = BrowserConfig.model_construct(
        headless=False,
        slow_mo=0,
        show_mouse_cursor=True,
        keep_browser_open=False,
    )
    assert cfg.headless is False
    assert cfg.show_mouse_cursor is True
    assert cfg.keep_browser_open is False
    assert cfg.slow_mo == 0

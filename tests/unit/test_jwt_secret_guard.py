"""Unit tests for the P0 JWT secret startup guard (Settings model validator)."""

import pytest
from pydantic import ValidationError

from agent.core.config import Settings

FALLBACK = "super-secret-local-development-key"
STRONG = "a-very-long-random-secret-key-for-tests-0123456789abcdef"


def _make(**overrides) -> Settings:
    """Build Settings with explicit alias-keyed values (aliases override env file)."""
    base = {
        "UAT_RUNTIME_MODE": "local",
        "ENVIRONMENT": "development",
        "JWT_SECRET_KEY": STRONG,
    }
    base.update(overrides)
    return Settings(**base)


class TestJwtSecretGuard:
    def test_local_dev_with_fallback_secret_is_allowed(self) -> None:
        """Local development keeps the documented fallback behavior (warns, does not fail)."""
        with pytest.warns(UserWarning, match="JWT_SECRET_KEY"):
            s = _make(JWT_SECRET_KEY=FALLBACK)
        assert s.jwt_secret_key == FALLBACK

    def test_local_dev_with_explicit_secret_is_allowed(self) -> None:
        s = _make()
        assert s.jwt_secret_key == STRONG

    def test_docker_runtime_with_fallback_secret_fails(self) -> None:
        """Production/container startup must fail on the well-known fallback."""
        with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
            _make(UAT_RUNTIME_MODE="docker", ENVIRONMENT="production", JWT_SECRET_KEY=FALLBACK)

    def test_docker_runtime_with_empty_secret_fails(self) -> None:
        with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
            _make(UAT_RUNTIME_MODE="docker", ENVIRONMENT="production", JWT_SECRET_KEY="")

    def test_docker_runtime_with_short_secret_fails(self) -> None:
        with pytest.raises(ValidationError, match="strong secret"):
            _make(
                UAT_RUNTIME_MODE="docker",
                ENVIRONMENT="production",
                JWT_SECRET_KEY="short-but-not-the-fallback",
            )

    def test_docker_runtime_with_strong_secret_passes(self) -> None:
        s = _make(UAT_RUNTIME_MODE="docker", ENVIRONMENT="production")
        assert s.jwt_secret_key == STRONG

    def test_non_dev_environment_with_fallback_fails(self) -> None:
        """Even runtime_mode=local must not run 'validation'/'production' on the fallback."""
        with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
            _make(ENVIRONMENT="validation", JWT_SECRET_KEY=FALLBACK)

    def test_non_dev_environment_with_strong_secret_passes(self) -> None:
        s = _make(ENVIRONMENT="validation")
        assert s.jwt_secret_key == STRONG

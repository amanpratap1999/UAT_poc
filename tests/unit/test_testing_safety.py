"""Unit tests for exploratory safety policy."""

import pytest

from agent.testing.safety import ExploratorySafetyPolicy, SafetyViolationError


def test_exploratory_safe_action():
    # Valid exploratory actions
    assert ExploratorySafetyPolicy.validate_step("Submit the form twice rapidly") is True
    assert ExploratorySafetyPolicy.validate_step("Leave mandatory field blank") is True
    assert ExploratorySafetyPolicy.validate_step("Refresh the page during loading") is True


def test_exploratory_safety_rejection():
    # Banned actions should raise SafetyViolationError
    with pytest.raises(SafetyViolationError, match="restricted pattern"):
        ExploratorySafetyPolicy.validate_step("Delete the current record")

    with pytest.raises(SafetyViolationError, match="restricted pattern"):
        ExploratorySafetyPolicy.validate_step("Perform a bulk update on all incidents")

    with pytest.raises(SafetyViolationError, match="restricted pattern"):
        ExploratorySafetyPolicy.validate_step("Modify permission for the user role")

    with pytest.raises(SafetyViolationError, match="restricted pattern"):
        ExploratorySafetyPolicy.validate_step("Create user admin")

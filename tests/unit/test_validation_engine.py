"""Unit tests for the Validation Engine."""

from __future__ import annotations

import pytest

from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.observation import ButtonInfo, FieldInfo, PageObservation
from agent.core.types import PageType
from agent.validation.engine import ValidationEngine


@pytest.fixture
def engine() -> ValidationEngine:
    return ValidationEngine()


@pytest.fixture
def before_observation() -> PageObservation:
    """Page state before action."""
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc",
        title="Incident",
        page_type=PageType.FORM,
        current_state="New",
        visible_fields=[
            FieldInfo(name="Short Description", value="", is_mandatory=True),
        ],
        buttons=[ButtonInfo(label="Update")],
        validation_messages=[],
    )


@pytest.fixture
def after_observation_success() -> PageObservation:
    """Page state after successful fill."""
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc",
        title="Incident",
        page_type=PageType.FORM,
        current_state="New",
        visible_fields=[
            FieldInfo(name="Short Description", value="Test incident", is_mandatory=True),
        ],
        buttons=[ButtonInfo(label="Update")],
        validation_messages=[],
    )


@pytest.fixture
def after_observation_with_error() -> PageObservation:
    """Page state with new validation errors."""
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc",
        title="Incident",
        page_type=PageType.FORM,
        current_state="New",
        visible_fields=[
            FieldInfo(name="Short Description", value="", is_mandatory=True),
        ],
        buttons=[ButtonInfo(label="Update")],
        validation_messages=["Short Description is required"],
    )


@pytest.mark.asyncio
async def test_validate_successful_fill(
    engine: ValidationEngine,
    before_observation: PageObservation,
    after_observation_success: PageObservation,
) -> None:
    """Test validation of a successful fill action."""
    action = AgentAction(
        action_type=ActionType.FILL,
        target="label:Short Description",
        value="Test incident",
        reasoning="Fill description",
        metadata={"field_label": "Short Description"},
    )
    result = ActionResult(success=True, action=action, duration_ms=100)

    validation = await engine.validate_action(
        action=action,
        result=result,
        before=before_observation,
        after=after_observation_success,
    )

    assert validation.overall_passed is True
    assert len(validation.checks) >= 2  # action_execution + no_new_errors


@pytest.mark.asyncio
async def test_validate_failed_action(
    engine: ValidationEngine,
    before_observation: PageObservation,
    after_observation_with_error: PageObservation,
) -> None:
    """Test validation when action failed."""
    action = AgentAction(
        action_type=ActionType.CLICK,
        target="text:Update",
        reasoning="Click update",
    )
    result = ActionResult(
        success=False,
        action=action,
        error="Element not found",
        error_type="SelectorNotFoundError",
    )

    validation = await engine.validate_action(
        action=action,
        result=result,
        before=before_observation,
        after=after_observation_with_error,
    )

    assert validation.overall_passed is False
    assert any(
        c.check_name == "action_execution" and not c.passed
        for c in validation.checks
    )


@pytest.mark.asyncio
async def test_validate_detects_new_errors(
    engine: ValidationEngine,
    before_observation: PageObservation,
    after_observation_with_error: PageObservation,
) -> None:
    """Test that new validation messages are detected."""
    action = AgentAction(
        action_type=ActionType.CLICK,
        target="text:Update",
        reasoning="Click",
    )
    result = ActionResult(success=True, action=action)

    validation = await engine.validate_action(
        action=action,
        result=result,
        before=before_observation,
        after=after_observation_with_error,
    )

    error_check = next(
        (c for c in validation.checks if c.check_name == "no_new_errors"),
        None,
    )
    assert error_check is not None
    assert error_check.passed is False


@pytest.mark.asyncio
async def test_validate_js_errors(
    engine: ValidationEngine,
    before_observation: PageObservation,
    after_observation_success: PageObservation,
) -> None:
    """Test JavaScript error detection."""
    action = AgentAction(
        action_type=ActionType.CLICK,
        target="button",
        reasoning="test",
    )
    result = ActionResult(success=True, action=action)

    validation = await engine.validate_action(
        action=action,
        result=result,
        before=before_observation,
        after=after_observation_success,
        console_errors=["Uncaught TypeError: Cannot read property 'x'"],
    )

    js_check = next(
        (c for c in validation.checks if c.check_name == "no_js_errors"),
        None,
    )
    assert js_check is not None
    assert js_check.passed is False


@pytest.mark.asyncio
async def test_validation_result_summary(
    engine: ValidationEngine,
    before_observation: PageObservation,
    after_observation_success: PageObservation,
) -> None:
    """Test that validation result produces a summary."""
    action = AgentAction(action_type=ActionType.CLICK, target="btn", reasoning="test")
    result = ActionResult(success=True, action=action)

    validation = await engine.validate_action(
        action=action,
        result=result,
        before=before_observation,
        after=after_observation_success,
    )

    summary = validation.to_summary()
    assert "Validation" in summary
    assert "checks passed" in summary

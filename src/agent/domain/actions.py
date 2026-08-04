"""Action models — the structured commands the planner emits.

The planner never touches Playwright. It emits AgentAction instances,
which the ExecutionController translates into browser operations.
Each action carries a 'reasoning' field so the LLM's intent is auditable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.core.types import ActionType


class AgentAction(BaseModel):
    """Base action model emitted by the planner.

    Every action the agent takes is represented as a structured command.
    The execution controller dispatches based on `action_type`.
    """

    model_config = ConfigDict(use_enum_values=True)

    action_type: ActionType
    target: str = Field(
        default="",
        description="Element identifier: label, role, text, or CSS selector",
    )
    value: str = Field(
        default="",
        description="Value to fill, option to select, URL to navigate to, etc.",
    )
    reasoning: str = Field(
        default="",
        description="LLM's reasoning for choosing this action",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (e.g., wait duration, scroll direction)",
    )


class ClickAction(AgentAction):
    """Click on an element identified by target."""

    action_type: Literal[ActionType.CLICK] = ActionType.CLICK


class FillAction(AgentAction):
    """Fill a form field with a value."""

    action_type: Literal[ActionType.FILL] = ActionType.FILL
    field_label: str = Field(default="", description="Human-readable field label")


class SelectAction(AgentAction):
    """Select an option from a dropdown or choice list."""

    action_type: Literal[ActionType.SELECT] = ActionType.SELECT
    field_label: str = Field(default="", description="Human-readable field label")


class NavigateAction(AgentAction):
    """Navigate to a URL."""

    action_type: Literal[ActionType.NAVIGATE] = ActionType.NAVIGATE
    url: str = Field(default="", description="Full URL to navigate to")


class WaitAction(AgentAction):
    """Wait for a condition or duration."""

    action_type: Literal[ActionType.WAIT] = ActionType.WAIT
    wait_for: Literal["load", "network_idle", "element", "duration"] = "load"
    duration_ms: int = Field(default=2000, description="Wait duration in ms")


class KeyPressAction(AgentAction):
    """Press a keyboard key."""

    action_type: Literal[ActionType.KEY_PRESS] = ActionType.KEY_PRESS
    key: str = Field(default="Enter", description="Key to press (e.g., Enter, Tab, Escape)")


class ScrollAction(AgentAction):
    """Scroll the page or element."""

    action_type: Literal[ActionType.SCROLL] = ActionType.SCROLL
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = Field(default=300, description="Scroll amount in pixels")


class ValidateAction(AgentAction):
    """Explicit validation request from the planner."""

    action_type: Literal[ActionType.VALIDATE] = ActionType.VALIDATE
    expected_state: str = Field(default="", description="Expected page/field state")
    check_type: str = Field(default="page_state", description="What to validate")


class ScreenshotAction(AgentAction):
    """Take a screenshot of the current page."""

    action_type: Literal[ActionType.SCREENSHOT] = ActionType.SCREENSHOT
    name: str = Field(default="screenshot", description="Screenshot file name prefix")


class ActionResult(BaseModel):
    """Result of executing an action.

    Captures success/failure, timing, evidence (screenshot), and errors.
    """

    success: bool
    action: AgentAction
    duration_ms: float = 0.0
    screenshot_path: str | None = None
    error: str | None = None
    error_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

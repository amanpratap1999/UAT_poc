"""Custom exception hierarchy for the agent system.

All agent exceptions inherit from AgentError, providing a structured
error taxonomy that recovery and logging systems can pattern-match on.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base exception for all agent errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ---------------------------------------------------------------------------
# Planner errors
# ---------------------------------------------------------------------------

class PlannerError(AgentError):
    """Raised when the planner (LLM) fails to produce a valid response."""


class LLMConnectionError(PlannerError):
    """Raised when the LLM API is unreachable or returns a non-200 status."""


class LLMResponseParseError(PlannerError):
    """Raised when the LLM response cannot be parsed into expected structure."""


# ---------------------------------------------------------------------------
# Execution errors
# ---------------------------------------------------------------------------

class ExecutionError(AgentError):
    """Base class for errors during browser action execution."""


class SelectorNotFoundError(ExecutionError):
    """Raised when an element selector does not match any element on the page."""


class NavigationTimeoutError(ExecutionError):
    """Raised when a page navigation exceeds the configured timeout."""


class ElementStaleError(ExecutionError):
    """Raised when an element reference becomes stale (DOM re-rendered)."""


class ElementNotInteractableError(ExecutionError):
    """Raised when an element exists but cannot be interacted with."""


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class ValidationFailedError(AgentError):
    """Raised when a post-action validation check fails."""


# ---------------------------------------------------------------------------
# Recovery errors
# ---------------------------------------------------------------------------

class RecoveryExhaustedError(AgentError):
    """Raised when all recovery strategies have been exhausted."""

    def __init__(
        self,
        message: str,
        original_error: Exception | None = None,
        attempts: int = 0,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details)
        self.original_error = original_error
        self.attempts = attempts


# ---------------------------------------------------------------------------
# Browser errors
# ---------------------------------------------------------------------------

class BrowserError(AgentError):
    """Base class for browser-level errors."""


class BrowserLaunchError(BrowserError):
    """Raised when the browser fails to launch."""


class BrowserCrashedError(BrowserError):
    """Raised when the browser process crashes unexpectedly."""


# ---------------------------------------------------------------------------
# Agent lifecycle errors
# ---------------------------------------------------------------------------

class AgentMaxStepsExceededError(AgentError):
    """Raised when the agent exceeds the maximum allowed steps."""


class AgentGoalUnachievableError(AgentError):
    """Raised when the planner determines the goal cannot be achieved."""

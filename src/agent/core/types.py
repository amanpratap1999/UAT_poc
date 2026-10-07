"""Shared type definitions, enumerations, and type aliases.

These types form the shared vocabulary of the agent system. Every module
imports from here rather than defining its own action/state enums.
"""

from __future__ import annotations

from enum import StrEnum


class ActionType(StrEnum):
    """Types of browser actions the agent can perform."""

    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    NAVIGATE = "navigate"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    EXTRACT = "extract"
    SCROLL = "scroll"
    KEY_PRESS = "key_press"
    VALIDATE = "validate"
    VALIDATE_FIELD = "validate_field"
    VALIDATE_STATE = "validate_state"
    VALIDATE_ERRORS = "validate_errors"


class AgentState(StrEnum):
    """High-level states of the agent runtime."""

    IDLE = "idle"
    INTENT_ANALYSIS = "intent_analysis"
    PLANNING = "planning"
    OBSERVING = "observing"
    REASONING = "reasoning"
    DECISION = "decision"
    EXECUTING = "executing"
    VALIDATING = "validating"
    REFLECTION = "reflection"
    RECOVERING = "recovering"
    LEARNING = "learning"
    COMPLETED = "completed"
    FAILED = "failed"
    CLEANUP_FAILED = "cleanup_failed"
    PRECONDITION_FAILED = "precondition_failed"
    BLOCKED = "blocked"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    AWAITING_USER_INPUT = "awaiting_user_input"


class ToolCategory(StrEnum):
    """Categories of tools available in the registry."""

    BROWSER = "browser"
    VALIDATION = "validation"
    KNOWLEDGE = "knowledge"
    REPORTING = "reporting"


class StepStatus(StrEnum):
    """Status of an individual plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class RunEventType(StrEnum):
    """Canonical event types emitted during live agent execution."""

    RUN_STARTED = "run_started"
    INTENT_PARSED = "intent_parsed"
    PLAN_CREATED = "plan_created"
    PRECONDITION_CHECK_STARTED = "precondition_check_started"
    PRECONDITION_CHECK_PASSED = "precondition_check_passed"
    PRECONDITION_CHECK_FAILED = "precondition_check_failed"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    CLARIFICATION_REQUESTED = "clarification_requested"
    APPROVAL_PROMPT = "approval_prompt"
    RUN_PAUSED = "run_paused"
    RUN_RESUMED = "run_resumed"
    RUN_CANCELLED = "run_cancelled"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"

    # Backward-compatible mappings
    ACTION_STARTED = "step_started"
    ACTION_COMPLETED = "step_finished"
    APPROVAL_REQUIRED = "approval_prompt"
    USER_INPUT_REQUIRED = "clarification_requested"
    RUN_COMPLETED = "run_finished"


class RunControlStatus(StrEnum):
    """Shared control status constants."""

    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    AWAITING_USER_INPUT = "awaiting_user_input"
    AWAITING_APPROVAL = "awaiting_approval"


class PageType(StrEnum):
    """Detected page types in ServiceNow."""

    FORM = "form"
    LIST = "list"
    DASHBOARD = "dashboard"
    DIALOG = "dialog"
    LOGIN = "login"
    HOMEPAGE = "homepage"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    """Defect severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RecoveryStrategy(StrEnum):
    """Available recovery strategies for the recovery engine."""

    WAIT_AND_RETRY = "wait_and_retry"
    RELOCATE_ELEMENT = "relocate_element"
    DISMISS_DIALOG = "dismiss_dialog"
    SCROLL_INTO_VIEW = "scroll_into_view"
    REFRESH_PAGE = "refresh_page"
    ESCALATE_TO_PLANNER = "escalate_to_planner"

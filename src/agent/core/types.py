"""Shared type definitions, enumerations, and type aliases.

These types form the shared vocabulary of the agent system. Every module
imports from here rather than defining its own action/state enums.
"""

from __future__ import annotations

from enum import Enum


class ActionType(str, Enum):
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


class AgentState(str, Enum):
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


class ToolCategory(str, Enum):
    """Categories of tools available in the registry."""

    BROWSER = "browser"
    VALIDATION = "validation"
    KNOWLEDGE = "knowledge"
    REPORTING = "reporting"


class StepStatus(str, Enum):
    """Status of an individual plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PageType(str, Enum):
    """Detected page types in ServiceNow."""

    FORM = "form"
    LIST = "list"
    DASHBOARD = "dashboard"
    DIALOG = "dialog"
    LOGIN = "login"
    HOMEPAGE = "homepage"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    """Defect severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RecoveryStrategy(str, Enum):
    """Available recovery strategies for the recovery engine."""

    WAIT_AND_RETRY = "wait_and_retry"
    RELOCATE_ELEMENT = "relocate_element"
    DISMISS_DIALOG = "dismiss_dialog"
    SCROLL_INTO_VIEW = "scroll_into_view"
    REFRESH_PAGE = "refresh_page"
    ESCALATE_TO_PLANNER = "escalate_to_planner"

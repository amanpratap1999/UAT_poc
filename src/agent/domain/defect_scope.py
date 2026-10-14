"""Defect-scope classification — the single source of truth for what
qualifies as an application defect versus an agent/execution issue.

Conceptual separation (product requirement):

- **Application defect** — the QA execution produced sufficient evidence that
  the ServiceNow application itself did not behave according to expected
  business/application behavior (e.g. a valid state transition is rejected,
  a field persists the wrong value, a mandatory-field rule fails).

- **Agent / execution issue** — the QA system was unable to successfully
  perform, observe, reason about, or verify the test (element not found,
  perception/grounding failure, timeout, retry, browser error, inconclusive
  behavioral verification, internal runtime error).

Agent-side problems must never inflate the application defect count. They
remain valuable diagnostics for the QA engine itself.

The classification is deterministic and evidence-based:

1. If the ActionResult of a step failed, the agent never successfully
   performed the interaction, so nothing about application behavior can be
   concluded — the step's failure is agent-side, regardless of which
   validation checks failed alongside it.
2. Otherwise, the failed validation checks are classified by scope:
   agent-capability/observability checks (``action_execution``,
   ``page_responded``, ``behavioral_verification``) are agent-side;
   application-behavior checks (``field_update``, ``state_change``,
   ``page_navigation``, ``no_new_errors``, ``no_new_js_errors``,
   ``no_network_errors``) are application-scope, as are unknown check names
   (e.g. skill-level business-rule checks) — when evidence is inconclusive
   we route to investigation rather than silently discarding the signal.
"""

from __future__ import annotations

from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Agent/runtime error types (from core.exceptions + producers)
# ---------------------------------------------------------------------------

#: Error types that mean "the QA engine failed to perform the interaction".
#: If ActionResult.error_type is one of these, the step is an agent issue.
AGENT_ERROR_TYPES: frozenset[str] = frozenset(
    {
        # core.exceptions hierarchy
        "AgentError",
        "PlannerError",
        "LLMConnectionError",
        "LLMResponseParseError",
        "ExecutionError",
        "SelectorNotFoundError",
        "ElementNotInteractableError",
        "NavigationTimeoutError",
        "ElementStaleError",
        "RecoveryExhaustedError",
        "BrowserError",
        "BrowserLaunchError",
        "BrowserCrashedError",
        "AgentMaxStepsExceededError",
        "AgentGoalUnachievableError",
        # ExecutionController policy/dispatch outcomes
        "PolicyBlockedError",
        "UnknownActionType",
        # Perception layer outcomes
        "GroundingFailure",
        "PerceptionFailure",
        "VerificationFailure",
        # Cognitive loop planning failures
        "PlanningFailure",
    }
)

#: Validation checks that measure the agent's own capability to execute or
#: observe — a failure here says nothing about the application.
AGENT_SCOPE_CHECKS: frozenset[str] = frozenset(
    {
        "action_execution",  # the agent failed to perform the interaction
        "page_responded",  # the agent could not establish a visible change
        "behavioral_verification",  # verification was inconclusive (agent-side)
    }
)

#: The marker error_type used by the cognitive loop for mismatches that the
#: InvestigationEngine confirmed as genuine application defects.
VERIFIED_DEFECT_ERROR_TYPE = "InvestigationVerifiedDefect"


def is_agent_error_type(error_type: Any) -> bool:
    """Whether an ActionResult error_type indicates an agent-side failure."""
    return isinstance(error_type, str) and error_type in AGENT_ERROR_TYPES


def is_agent_scope_check(check_name: Any) -> bool:
    """Whether a validation check measures agent capability (not app behavior)."""
    return isinstance(check_name, str) and check_name in AGENT_SCOPE_CHECKS


def _failed_checks(validation: Any) -> list[Any] | None:
    """Defensively extract failed checks; None when the shape is unknown."""
    try:
        checks = getattr(validation, "checks", None)
        if isinstance(checks, (list, tuple)):
            return [c for c in checks if getattr(c, "passed", True) is False]
        return None
    except Exception:
        return None


def classify_step_failure(result: Any, validation: Any) -> str | None:
    """Classify why a step's validation failed.

    Args:
        result: The ActionResult for the step (may be None in tests).
        validation: The ValidationResult for the step (may be None/Mock).

    Returns:
        ``"agent"`` — the failure is attributable to the QA engine.
        ``"application"`` — the failure is application-behavior evidence and
            should be routed to investigation.
        ``None`` — no failure to classify.
    """
    # 1. Precondition failure: initial environment/record state mismatch before mutation
    if getattr(validation, "precondition_failed", False) is True:
        return "precondition"

    # 2. The interaction itself failed — nothing about the app can be concluded.
    try:
        success = getattr(result, "success", None)
        if success is False:
            return "agent"
    except Exception:
        return "agent"

    failed = _failed_checks(validation)
    if failed is None:
        # Unknown validation shape (e.g. opaque mock): default to application
        # scope so the mismatch is investigated rather than discarded.
        return "application"
    if not failed:
        return None

    # 3. Any failed agent-capability check makes the step agent-side.
    for check in failed:
        if is_agent_scope_check(getattr(check, "check_name", None)):
            return "agent"

    # 3. Remaining failed checks are application-behavior evidence.
    return "application"

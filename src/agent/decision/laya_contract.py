"""LAYA Decision Contract (P1-02).

Typed decision contract for LAYA — a bounded decision model that
classifies, routes, and scores information. LAYA is NOT a generative
planner or browser executor. It makes bounded decisions that the
orchestrator validates before acting.

P1-02: LAYA must not be treated as a generative planner or browser
executor. This module defines the typed decision contract that
restricts LAYA to: intent classification, workflow routing, risk
classification, verification_needed decisions, and escalation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Any

# Bounded decision types LAYA can make
DecisionType = Literal["intent", "route", "risk", "verification_needed", "escalation"]

# Escalation levels
EscalationLevel = Literal["continue", "fallback", "human_review", "abort"]


@dataclass
class LayaDecision:
    """A typed decision from LAYA.

    P1-02: LAYA returns bounded decisions, not free-form text.
    The orchestrator validates each decision before acting.
    """
    decision_type: DecisionType
    value: str  # the selected option (e.g., "create_incident", "itil", "high")
    confidence: float  # 0.0-1.0
    reasoning: str = ""  # brief explanation (not used for execution)
    escalation: EscalationLevel = "continue"  # whether to escalate
    metadata: dict[str, Any] = field(default_factory=dict)  # additional structured data
    # P1-06: provider selection + fallback traceability
    provider: str = "laya"  # which provider made this decision
    fallback_reason: str = ""  # if this was a fallback, why


# Supported intent operations (bounded set)
SUPPORTED_INTENTS = frozenset({
    "create_incident",
    "update_incident",
    "resolve_incident",
    "reopen_incident",
    "assign_incident",
    "verify_incident_state",
    "verify_priority",
    "verify_assignment",
    "verify_mandatory_fields",
    "verify_state_transition",
    "verify_acl",
    "verify_notification",
    "verify_sla",
    "verify_dependent_choice",
    "detect_defect",
    "exploratory_pass",
})

# Supported workflow routes
SUPPORTED_ROUTES = frozenset({
    "incident_lifecycle",
    "incident_creation",
    "incident_resolution",
    "incident_assignment",
    "incident_acl_check",
    "incident_notification_check",
    "incident_sla_check",
    "incident_defect_detection",
    "incident_exploratory",
})

# Unsupported categories (LAYA should reject these)
UNSUPPORTED_CATEGORIES = frozenset({
    "change_management",
    "catalog",
    "hrsd",
    "csm",
    "itam",
    "itom",
})

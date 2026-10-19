"""C13: Dependent-choice and UI-policy probe for ServiceNow Incident forms."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.domain.observation import PageObservation
from agent.domain.validation import ValidationCheck


@dataclass
class FieldPolicyState:
    """Observed mandatory, read-only, and visible state for a form field."""
    name: str
    mandatory: bool = False
    read_only: bool = False
    visible: bool = True
    options: list[str] = field(default_factory=list)


class IncidentUiPolicyProbe:
    """Probes mandatory/read-only field policies and dependent choice options per state."""

    @staticmethod
    def extract_field_policy_map(observation: PageObservation) -> dict[str, FieldPolicyState]:
        """Build a map of field name -> FieldPolicyState from a PageObservation."""
        policy_map: dict[str, FieldPolicyState] = {}
        for f in getattr(observation, "visible_fields", []) or []:
            key = (getattr(f, "name", "") or "").strip().lower().replace("incident.", "")
            if not key:
                continue
            policy_map[key] = FieldPolicyState(
                name=key,
                mandatory=bool(getattr(f, "is_mandatory", False) or getattr(f, "required", False) or getattr(f, "mandatory", False)),
                read_only=bool(getattr(f, "is_readonly", False) or getattr(f, "readonly", False) or getattr(f, "read_only", False) or getattr(f, "disabled", False)),
                visible=True,
                options=list(getattr(f, "options", []) or []),
            )
        return policy_map

    @classmethod
    def verify_mandatory_fields_for_state(
        cls,
        observation: PageObservation,
        expected_mandatory_fields: list[str],
    ) -> list[ValidationCheck]:
        """Verify that every expected mandatory field for the current state is marked mandatory."""
        policy_map = cls.extract_field_policy_map(observation)
        checks: list[ValidationCheck] = []
        for req_field in expected_mandatory_fields:
            norm = req_field.strip().lower().replace(" ", "_")
            state = policy_map.get(norm) or policy_map.get(req_field.strip().lower())
            is_mandatory = bool(state and state.mandatory)
            checks.append(
                ValidationCheck(
                    check_name="ui_policy_mandatory",
                    description=f"Field '{req_field}' is mandatory under current UI policy",
                    passed=is_mandatory,
                    expected="mandatory=True",
                    actual=f"mandatory={is_mandatory}" if state else "field_not_visible",
                    error_message=None if is_mandatory else f"Field '{req_field}' is not marked mandatory",
                )
            )
        return checks

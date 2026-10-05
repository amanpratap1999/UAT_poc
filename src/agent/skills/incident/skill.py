"""IncidentSkill Core implementation for Deliverable 3.

The IncidentSkill plugin encapsulates all ServiceNow Incident Management logic:
- Domain Intent Matching
- Execution Plan Construction
- Navigation & Action Generation
- Observation & Domain Model Conversion
- Lifecycle & Business Rule Validation
- Incident-Specific Error Recovery
- Evidence Collection
"""

from __future__ import annotations

from typing import Any

from agent.capabilities.registry import CapabilityDefinition
from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.plan import ExecutionPlan
from agent.domain.skill import SkillManifest
from agent.domain.validation import ValidationResult
from agent.domain.world import SemanticWorldState
from agent.skills.base import BaseSkill
from agent.skills.incident.evidence import EvidenceCollector
from agent.skills.incident.lifecycle import LifecycleEngine
from agent.skills.incident.navigation import IncidentNavigator
from agent.skills.incident.observation import IncidentObserver
from agent.skills.incident.recovery import IncidentRecoveryHandler
from agent.skills.incident.validation import IncidentValidator

logger = get_logger(__name__)


class IncidentSkill(BaseSkill):
    """Production Domain Skill for ServiceNow Incident Management."""

    def __init__(self, config: Any = None) -> None:
        self._config = config
        base_url = getattr(config, "instance_url", "") if config else ""
        if not base_url:
            from agent.core.config import get_settings
            base_url = get_settings().servicenow.instance_url or "https://localhost"
        base_url = base_url.rstrip("/")
        self._navigator = IncidentNavigator(base_url=base_url)
        self._observer = IncidentObserver()
        self._lifecycle_engine = LifecycleEngine()
        self._validator = IncidentValidator()
        self._recovery_handler = IncidentRecoveryHandler()
        self._evidence_collector = EvidenceCollector()
        self._oracle = None
        self._side_effect_validator = None
        if config and getattr(config, "api_oracle_enabled", True) and getattr(config, "username", None):
            try:
                from agent.skills.incident.api_oracle import IncidentApiOracle
                from agent.skills.incident.side_effects import IncidentSideEffectValidator
                self._oracle = IncidentApiOracle(config)
                self._side_effect_validator = IncidentSideEffectValidator(self._oracle)
            except Exception as e:
                logger.warning("incident_skill_oracle_init_failed", error=str(e))

    @property
    def manifest(self) -> SkillManifest:
        return SkillManifest(
            name="IncidentSkill",
            module="incident",
            version="2.1.0",
            description="ServiceNow Incident Management domain skill plugin",
            supported_intents=[
                "IncidentValidation",
                "IncidentCreation",
                "IncidentLifecycle",
                "IncidentOpen",
                "IncidentResolutionCheck",
                "IncidentAssignmentValidation",
                "IncidentMandatoryFieldsCheck",
            ],
        )

    @property
    def evidence_collector(self) -> EvidenceCollector:
        return self._evidence_collector

    def get_capability_definition(self) -> CapabilityDefinition:
        return CapabilityDefinition(
            name="Incident",
            module_name="incident",
            supported_tables=["incident", "incident_task"],
            description="ServiceNow Incident Management domain skill plugin",
        )

    def get_domain_selectors(self) -> dict[str, str | list[str]]:
        return {
            "record_number": [
                "input[name$='.number']",
                "input[id$='.number']",
                "[id^='sys_readonly.'][id$='.number']",
            ],
            "record_state": [
                "select[name$='.state']",
                "select[id$='.state']",
                "[id^='sys_readonly.'][id$='.state']",
                "[id*='state'] option[selected]",
            ],
        }

    def get_lifecycle_states(self) -> list[str]:
        return ["New", "In Progress", "On Hold", "Resolved", "Closed", "Canceled"]

    def can_handle(self, intent: StructuredIntent) -> bool:
        """Check if intent targets incident management."""
        intent_mod = intent.target_module.lower()
        if intent_mod in ("incident", "incident_task"):
            return (
                intent.intent_type in self.manifest.supported_intents
                or "incident" in intent.goal.lower()
                or "inc" in intent.goal.lower()
                or "incident" in intent.raw_prompt.lower()
            )
        return (
            "incident" in intent.goal.lower()
            or "incident" in intent.raw_prompt.lower()
            or (intent.intent_type in self.manifest.supported_intents and intent_mod != "auth" and intent_mod != "general")
        )

    async def plan(
        self, intent: StructuredIntent, world_state: SemanticWorldState | None = None
    ) -> ExecutionPlan:
        """Build a domain-specific execution plan for the incident goal.

        P1-05 (D1–D4): now also recognizes the full Incident workflow
        vocabulary (creation / assignment / on-hold / resolution / closure
        / reopen / cancel / inspection). Each step carries a
        ``requirement_id`` so the reporting engine can trace step →
        acceptance criterion. The previous keyword branches (state /
        lifecycle / open / resolve / assignment / mandatory / default)
        are preserved as fall-backs.
        """
        logger.info(
            "building_incident_execution_plan", goal=intent.goal, intent_type=intent.intent_type
        )
        plan = ExecutionPlan(goal=intent.goal)

        goal_lower = intent.goal.lower()

        # Explicit read-only intent takes precedence over incidental mentions
        # of "state", "lifecycle", or "resolve" in the requested fields. A
        # smoke check that asks to observe state must never become a lifecycle
        # mutation plan.
        read_only_markers = (
            "read-only",
            "read only",
            "do not change",
            "do not modify",
            "do not update",
            "inspect only",
            "observe only",
            "no mutations",
        )
        if any(marker in goal_lower for marker in read_only_markers):
            plan.add_step("Open Target Incident Record", "Requested Incident is displayed in the form", requirement_id="AC-WF08-01")
            plan.add_step("Observe Requested Incident Fields", "Requested values are read from the visible form", requirement_id="AC-WF08-01")
            plan.add_step("Re-observe Without Saving", "The same Incident remains unchanged after read-only verification", requirement_id="AC-WF08-02")
            return plan

        # P1-05: explicit workflow branches covering the full Incident
        # lifecycle. The step text and expected_outcome are matched by
        # the ScenarioGenerator and benchmark runner to the structured
        # acceptance criteria in ``incident_workflows.py``.
        if "create" in goal_lower and ("incident" in goal_lower or "inc" in goal_lower) and "new" in goal_lower:
            plan.add_step("Open New Incident Form", "Form displayed", requirement_id="AC-WF01-01")
            plan.add_step("Fill Short Description, Caller, Impact, Urgency", "Mandatory fields populated", requirement_id="AC-WF01-02")
            plan.add_step("Submit New Incident", "Incident created with generated INC number", requirement_id="AC-WF01-03")
            plan.add_step("Verify State is New (1)", "State observed as New", requirement_id="AC-WF01-01")
            return plan

        if ("on hold" in goal_lower or "hold" in goal_lower) and "inc" in goal_lower:
            plan.add_step("Open Target Incident Record", "Target incident form displayed", requirement_id="AC-WF03-01")
            plan.add_step("Set State to On Hold (3)", "State changed to On Hold", requirement_id="AC-WF03-01")
            plan.add_step("Set On Hold Reason to Awaiting Caller", "Hold reason populated", requirement_id="AC-WF03-02")
            plan.add_step("Populate Additional Comments", "Conditional mandatory field satisfied", requirement_id="AC-WF03-02")
            plan.add_step("Click Update to Persist", "On Hold transition saved", requirement_id="AC-WF03-01")
            plan.add_step("Verify SLA Paused", "SLA clock paused", requirement_id="AC-WF03-03")
            return plan

        if "close" in goal_lower and "inc" in goal_lower and "resolve" not in goal_lower:
            plan.add_step("Open Target Resolved Incident", "Incident form opened in Resolved state", requirement_id="AC-WF05-01")
            plan.add_step("Set State to Closed (7)", "State changed to Closed", requirement_id="AC-WF05-01")
            plan.add_step("Click Update to Persist", "Closure saved", requirement_id="AC-WF05-01")
            plan.add_step("Verify close_code Retained", "close_code persisted from resolution", requirement_id="AC-WF05-02")
            return plan

        if "reopen" in goal_lower and "inc" in goal_lower:
            plan.add_step("Open Target Closed Incident", "Incident form opened in Closed state", requirement_id="AC-WF06-01")
            plan.add_step("Populate Reopen Justification in Comments", "Justification captured", requirement_id="AC-WF06-03")
            plan.add_step("Set State to In Progress (2)", "State changed back to In Progress", requirement_id="AC-WF06-01")
            plan.add_step("Click Update to Persist", "Reopen saved", requirement_id="AC-WF06-01")
            plan.add_step("Verify SLA Restarted", "SLA clock restarted", requirement_id="AC-WF06-02")
            plan.add_step("Verify Reopen Notification Fired", "incident.reopened notification sent", requirement_id="AC-WF06-03")
            return plan

        if "cancel" in goal_lower and "inc" in goal_lower:
            plan.add_step("Open Target Incident Record", "Incident form opened", requirement_id="AC-WF07-01")
            plan.add_step("Set State to Canceled (8)", "State changed to Canceled", requirement_id="AC-WF07-01")
            plan.add_step("Click Update to Persist", "Cancellation saved", requirement_id="AC-WF07-01")
            plan.add_step("Verify Form is Read-Only After Cancel", "No further mutations permitted", requirement_id="AC-WF07-02")
            return plan

        # Existing keyword branches preserved below — these cover the
        # lifecycle / open / resolve / assignment / mandatory / default
        # patterns and remain valid for backward compatibility.

        if ("state" in goal_lower or "lifecycle" in goal_lower or "in progress" in goal_lower or "on hold" in goal_lower) and "inc" in goal_lower:
            plan.add_step("Open Target Incident Record", "Target incident form displayed", requirement_id="AC-WF02-03")
            plan.add_step("Validate Initial Incident State and Preconditions", "Preconditions met: incident number and initial state match expectation", requirement_id="AC-WF02-03")
            plan.add_step("Update State to In Progress", "State dropdown changed to In Progress (2)", requirement_id="AC-WF02-03")
            plan.add_step("Click Update to Persist Record", "Incident changes saved", requirement_id="AC-WF02-03")
            plan.add_step("Re-open and Validate Incident State", "Persisted State is In Progress (2)", requirement_id="AC-WF02-03")
        elif "open" in goal_lower and "inc" in goal_lower:
            plan.add_step("Navigate to Incident List", "Incident list page displayed", requirement_id="AC-WF08-01")
            plan.add_step("Search and Open Target Incident", "Incident record opened", requirement_id="AC-WF08-01")
            plan.add_step("Validate Initial Incident State and Preconditions", "Incident record and initial state verified", requirement_id="AC-WF08-01")
            plan.add_step("Verify Incident Record Details", "Incident details verified", requirement_id="AC-WF08-01")
        elif "resolve" in goal_lower or "resolution" in goal_lower:
            plan.add_step("Open Existing Incident", "Incident record opened", requirement_id="AC-WF04-01")
            plan.add_step("Populate Resolution Code & Notes", "Resolution fields filled", requirement_id="AC-WF04-02")
            plan.add_step("Update State to Resolved", "Incident state is Resolved", requirement_id="AC-WF04-01")
            plan.add_step("Validate Resolution Outcome", "Resolution verified", requirement_id="AC-WF04-01")
        elif "assignment" in goal_lower:
            plan.add_step("Open Incident Form", "Incident form displayed", requirement_id="AC-WF02-01")
            plan.add_step("Update Assignment Group & Assigned To", "Assignment updated", requirement_id="AC-WF02-01")
            plan.add_step("Validate Assignment Update", "Assignment group verified", requirement_id="AC-WF02-01")
        elif "mandatory" in goal_lower:
            plan.add_step("Open New Incident Form", "New Incident form displayed", requirement_id="AC-WF01-01")
            plan.add_step("Inspect Mandatory Fields", "Mandatory indicators checked", requirement_id="AC-WF01-02")
            plan.add_step("Validate Mandatory Fields Rule", "Mandatory rule verified", requirement_id="AC-WF01-02")
        else:
            # Default complete lifecycle plan
            plan.add_step("Navigate to Incident Management", "Incident list view displayed", requirement_id="AC-WF01-01")
            plan.add_step(
                "Open an Existing Incident in New State", "Incident form displayed in New state", requirement_id="AC-WF01-01"
            )
            plan.add_step("Update Assignment Group", "Assignment group populated", requirement_id="AC-WF02-01")
            plan.add_step("Move State to In Progress", "State changed to In Progress", requirement_id="AC-WF02-03")
            plan.add_step(
                "Fill Resolution Details & Resolve",
                "Resolution code & notes populated, state is Resolved",
                requirement_id="AC-WF04-01",
            )
            plan.add_step("Validate Complete Lifecycle", "Complete Incident flow verified", requirement_id="AC-WF04-01")

        return plan

    async def validate(
        self,
        action: AgentAction,
        before: SemanticWorldState,
        after: SemanticWorldState,
    ) -> ValidationResult:
        """Validate business outcome between before and after world states."""
        logger.info("incident_skill_validating_action", action=action.action_type)

        incident_before = self._observer.parse_incident(
            before.model_copy() if hasattr(before, "model_copy") else before,
            before,
        )
        incident_after = self._observer.parse_incident(
            after.model_copy() if hasattr(after, "model_copy") else after,
            after,
        )

        metadata = action.metadata or {}
        is_precondition = (
            bool(metadata.get("is_precondition_check"))
            or getattr(action, "is_precondition_check", False)
            or "precondition" in (action.reasoning or "").lower()
            or "initial state" in (action.reasoning or "").lower()
            or "verify incident record" in (action.reasoning or "").lower()
            or "before proceeding" in (action.reasoning or "").lower()
        )

        if is_precondition:
            import re
            expected_rec = metadata.get("expected_record") or getattr(action, "expected_record", None)
            expected_st = metadata.get("expected_state") or getattr(action, "expected_state", None)
            if not expected_rec and (action.reasoning or ""):
                rec_m = re.search(r"\b(INC\d+)\b", action.reasoning or "", re.IGNORECASE)
                if rec_m:
                    expected_rec = rec_m.group(1).upper()
            if not expected_st and (action.reasoning or ""):
                st_m = re.search(r"(?:initial\s+state|state)\s*(?:is|to|as)?\s*([A-Za-z\s]+)", action.reasoning or "", re.IGNORECASE)
                if st_m:
                    cand = st_m.group(1).strip().lower()
                    for s in ("on hold", "in progress", "new", "resolved", "closed"):
                        if s in cand:
                            expected_st = s
                            break

            business_result = self._validator.validate_precondition(
                incident=incident_after,
                expected_record=expected_rec,
                expected_state=expected_st,
            )
            return self._validator.to_standard_validation_result(business_result, is_precondition=True)

        # Explicit expected state: a select action's value is the authoritative
        # post-action state ("2" / "In Progress"). Prefer action.value, then
        # metadata. Never guess from free-text reasoning when an explicit
        # value exists — that caused false positives when the reasoning
        # mentioned the from-state ("On Hold") alongside the to-state.
        expected_state: str | None = None
        if action.action_type.lower() == "select":
            expected_state = (action.value or "").strip() or None
        if not expected_state:
            expected_state = (metadata.get("expected_state") or "").strip() or None

        business_result = self._validator.validate_business_outcome(
            before=incident_before,
            after=incident_after,
            expected_step=action.reasoning or action.action_type,
            expected_state=expected_state,
        )

        # Record evidence item
        self._evidence_collector.record_evidence(
            step_description=action.reasoning or f"Action {action.action_type}",
            expected_result="Business rule satisfied",
            observed_result=f"State: {incident_after.state.name}, Priority: {incident_after.priority.name}",  # noqa: E501
            passed=business_result.passed,
            incident_number=incident_after.number,
            reasoning_summary=action.reasoning,
            confidence_score=0.95 if business_result.passed else 0.50,
        )

        standard_res = self._validator.to_standard_validation_result(business_result, is_precondition=False)
        if (
            self._side_effect_validator
            and getattr(incident_after, "sys_id", None)
            and getattr(incident_before, "state", None) != getattr(incident_after, "state", None)
        ):
            try:
                audit_check = await self._side_effect_validator.verify_audit_entry(
                    sys_id=str(incident_after.sys_id),
                    field="state",
                    expected_new=str(incident_after.state.value if hasattr(incident_after.state, "value") else incident_after.state),
                    since=str(getattr(incident_before, "sys_updated_on", "") or ""),
                )
                standard_res.add_check(audit_check)
                if not audit_check.passed:
                    standard_res.overall_passed = False
            except Exception as se_err:
                logger.warning("incident_skill_audit_check_failed", error=str(se_err))

        return standard_res

    async def recover(self, error: Exception, context: dict[str, Any]) -> AgentAction | None:
        """Suggest domain-specific recovery action."""
        logger.info("incident_skill_recovery_requested", error=str(error))

        return self._recovery_handler.suggest_incident_recovery(
            error_message=str(error),
            context=context,
        )

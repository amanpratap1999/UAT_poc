"""Incident Scenario Generator from Acceptance Criteria (INC-UAT-08).

Generates Incident test scenarios from natural-language acceptance
criteria, rather than relying on hardcoded plan branches.

INC-UAT-08 (Major, D1/D4): Incident scenario generation remains partly
hardcoded around a small set of goals. A human QA adapts scenarios from
requirements; narrow templates will miss client-specific behavior.
This module provides the generator that creates test scenarios from AC.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GeneratedScenario:
    """A test scenario generated from an acceptance criterion."""
    scenario_id: str
    requirement_id: str  # AC-001, AC-002, etc.
    acceptance_criterion: str
    test_type: str  # "positive" | "negative" | "boundary"
    description: str
    expected_outcome: str
    actions: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    risk_level: str = "Medium"


class IncidentScenarioGenerator:
    """Generates Incident test scenarios from acceptance criteria.

    INC-UAT-08 (Major, D1/D4): uses deterministic rules to parse
    acceptance criteria and generate positive, negative, and boundary
    test scenarios. The generator is NOT LLM-based (to keep it
    deterministic and reproducible) but can be extended to use an LLM
    for more complex criteria.

    The generator recognizes common Incident AC patterns:
    - "When <action>, then <expected>"
    - "<field> must be <value/constraint>"
    - "<transition> must <succeed/fail>"
    - "<persona> must be able to <action>"
    """

    # Regex patterns for common AC structures
    WHEN_THEN = re.compile(
        r"when\s+(.+?),?\s+then\s+(.+)", re.IGNORECASE
    )
    MUST_BE = re.compile(
        r"(.+?)\s+must\s+be\s+(.+)", re.IGNORECASE
    )
    MUST_SUCCEED = re.compile(
        r"(.+?)\s+must\s+(succeed|fail|be blocked|be allowed)", re.IGNORECASE
    )
    PERSONA_CAN = re.compile(
        r"(.+?)\s+must\s+be\s+able\s+to\s+(.+)", re.IGNORECASE
    )

    def generate_from_acceptance_criteria(
        self,
        criteria: list[dict[str, str]],
    ) -> list[GeneratedScenario]:
        """Generate test scenarios from a list of acceptance criteria.

        Args:
            criteria: list of dicts with 'requirement_id' and 'criterion' keys.
                e.g., [{"requirement_id": "AC-001", "criterion": "When a new
                Incident is created, then it must have Priority set to 4-Low by default"}]

        Returns:
            list of GeneratedScenario objects (typically 2-3 per criterion:
            one positive, one negative, optionally one boundary).
        """
        scenarios: list[GeneratedScenario] = []
        for i, ac in enumerate(criteria):
            req_id = ac.get("requirement_id", f"AC-{i+1:03d}")
            criterion = ac.get("criterion", "")
            if not criterion:
                continue
            generated = self._generate_for_criterion(req_id, criterion)
            scenarios.extend(generated)
        logger.info(
            "scenarios_generated",
            criteria_count=len(criteria),
            scenario_count=len(scenarios),
        )
        return scenarios

    def _generate_for_criterion(
        self, req_id: str, criterion: str
    ) -> list[GeneratedScenario]:
        """Generate positive + negative scenarios for one AC."""
        scenarios: list[GeneratedScenario] = []

        # Try each pattern
        when_then = self.WHEN_THEN.search(criterion)
        must_be = self.MUST_BE.search(criterion)
        must_succeed = self.MUST_SUCCEED.search(criterion)
        persona_can = self.PERSONA_CAN.search(criterion)

        if when_then:
            action = when_then.group(1).strip()
            expected = when_then.group(2).strip()
            # Positive: verify the expected outcome
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-POS",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="positive",
                description=f"Verify: {action} → {expected}",
                expected_outcome=expected,
                actions=[action],
            ))
            # Negative: violate the precondition and verify the expected does NOT happen
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-NEG",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="negative",
                description=f"Negate precondition: {action} does NOT occur → {expected} should NOT happen",
                expected_outcome=f"NOT: {expected}",
                actions=[f"do NOT {action}"],
                risk_level="High",
            ))

        elif must_be:
            field_name = must_be.group(1).strip()
            constraint = must_be.group(2).strip()
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-POS",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="positive",
                description=f"Verify: {field_name} is {constraint}",
                expected_outcome=f"{field_name} = {constraint}",
                actions=[f"check {field_name}"],
            ))
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-NEG",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="negative",
                description=f"Verify: {field_name} is NOT {constraint} triggers validation error",
                expected_outcome=f"{field_name} validation error",
                actions=[f"set {field_name} to invalid value"],
                risk_level="High",
            ))

        elif must_succeed:
            action = must_succeed.group(1).strip()
            outcome = must_succeed.group(2).strip()
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-POS",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="positive" if outcome == "succeed" or outcome == "be allowed" else "negative",
                description=f"Verify: {action} {outcome}",
                expected_outcome=f"{action} {outcome}",
                actions=[action],
            ))
            # Boundary: try the edge case
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-BND",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="boundary",
                description=f"Boundary: {action} with edge-case input",
                expected_outcome=f"{action} {outcome} with edge-case",
                actions=[f"{action} with empty input", f"{action} with max-length input"],
                risk_level="Medium",
            ))

        elif persona_can:
            persona = persona_can.group(1).strip()
            action = persona_can.group(2).strip()
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-POS",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="positive",
                description=f"{persona} performs: {action}",
                expected_outcome=f"{action} succeeds",
                actions=[f"as {persona}: {action}"],
            ))
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-NEG",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="negative",
                description=f"Different persona CANNOT: {action}",
                expected_outcome=f"{action} blocked for unauthorized persona",
                actions=[f"as different persona: attempt {action}"],
                risk_level="High",
            ))

        else:
            # Fallback: generate a generic positive scenario
            scenarios.append(GeneratedScenario(
                scenario_id=f"{req_id}-POS",
                requirement_id=req_id,
                acceptance_criterion=criterion,
                test_type="positive",
                description=f"Verify: {criterion}",
                expected_outcome=criterion,
                actions=[],
            ))

        return scenarios

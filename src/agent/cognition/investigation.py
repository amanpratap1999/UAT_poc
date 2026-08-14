"""Investigation Engine for handling expectation mismatches."""

from __future__ import annotations

from typing import Any

from agent.cognition.models import InvestigationResult
from agent.core.logging import get_logger
from agent.domain.knowledge_model import CustomerKnowledgeModel

logger = get_logger(__name__)


class InvestigationEngine:
    """Investigates unexpected outcomes to determine if they are true defects.

    Prevents false positives by checking observed behavior against known
    customer configurations (e.g. customizations, UI policies) or learned experiences.
    """

    def __init__(
        self,
        knowledge_model: CustomerKnowledgeModel | None = None,
        learning_service: Any | None = None,
    ) -> None:
        self._knowledge_model = knowledge_model
        self._learning_service = learning_service

    async def investigate_mismatch(
        self, action: Any, expected: str, actual: str, table_name: str | None = None
    ) -> InvestigationResult:
        """Investigate why actual behavior differed from expected.

        Args:
            action: The action that was executed.
            expected: The expected outcome.
            actual: The observed outcome (e.g., error message or missing field).
            table_name: Contextual table for knowledge lookup.

        Returns:
            InvestigationResult containing the classification.
        """
        logger.info("investigating_mismatch", expected=expected, actual=actual, table=table_name)

        # 1. Consult CustomerKnowledgeModel to see if this is a known customization
        explicitly_mandated_by_knowledge = False
        if self._knowledge_model and table_name:
            table_metadata = self._knowledge_model.get_table(table_name)
            if table_metadata:
                # E.g., if expected "field mandatory" but actually "optional"
                # We could check if it is explicitly optional in the knowledge model.
                # Since we don't have an LLM in this synchronous check, we'll do basic heuristics,
                # or delegate to a structured knowledge check.

                # Heuristic: Check if actual mentions a field that has specific UI policies
                for field_name, meta in table_metadata.fields.items():
                    if field_name.lower() in actual.lower() or (
                        meta.label and meta.label.lower() in actual.lower()
                    ):
                        # Check False Positives
                        if "mandatory" in expected.lower() and not meta.mandatory:
                            return InvestigationResult(
                                is_defect=False,
                                classification="false_positive_customization",
                                reasoning=f"Field '{field_name}' is not mandatory per CustomerKnowledgeModel.",  # noqa: E501
                                evidence=f"Knowledge model marks mandatory={meta.mandatory}",
                                knowledge_reference=f"Table:{table_name}:Field:{field_name}",
                            )
                        if "read only" in expected.lower() and not meta.read_only:
                            return InvestigationResult(
                                is_defect=False,
                                classification="false_positive_customization",
                                reasoning=f"Field '{field_name}' is not read-only per CustomerKnowledgeModel.",  # noqa: E501
                                evidence=f"Knowledge model marks read_only={meta.read_only}",
                                knowledge_reference=f"Table:{table_name}:Field:{field_name}",
                            )

                        # Protect Authority: If the knowledge model explicitly requires it, record it.  # noqa: E501
                        if "mandatory" in expected.lower() and meta.mandatory:
                            explicitly_mandated_by_knowledge = True

        # 2. Consult LearningService for historical explanations
        # Only allow learning to explain it if the authoritative knowledge model hasn't explicitly mandated it!  # noqa: E501
        if self._learning_service and table_name and not explicitly_mandated_by_knowledge:
            experiences = await self._learning_service.query_experiences(table_name)
            for exp in experiences:
                if (
                    exp.observation
                    and exp.observation.lower() in actual.lower()
                    and exp.outcome == "expected_customization"
                ):
                    return InvestigationResult(
                        is_defect=False,
                        classification="learned_customization",
                        reasoning=f"Matched historical experience: {exp.observation}",
                        evidence="Historical learning record",
                        knowledge_reference="LearningService",
                    )

        # 3. If no authoritative explanation exists, it is a verified defect
        return InvestigationResult(
            is_defect=True,
            classification="verified_defect",
            reasoning=f"No authoritative configuration found to explain: {actual}"
            + (
                " (Explicitly mandated by Knowledge Model)"
                if explicitly_mandated_by_knowledge
                else ""
            ),
            evidence=f"Expected: {expected} | Actual: {actual}",
        )

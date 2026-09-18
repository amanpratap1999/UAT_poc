"""Domain knowledge model and anomaly classification."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent.core.logging import get_logger

logger = get_logger(__name__)


class AnomalyClassification(StrEnum):
    """Types of observed anomalies in the ServiceNow instance."""

    BUSINESS_RULE_FAILURE = "Business Rule Failure"
    APPLICATION_BUG = "Application Bug"
    CONFIGURATION_DIFFERENCE = "Configuration Difference"
    EXPECTED_CUSTOMIZATION = "Expected Customization"
    UNKNOWN = "Unknown"
    INCONCLUSIVE = "Inconclusive"


class ClassificationResult(BaseModel):
    """Result of an anomaly classification."""

    classification: AnomalyClassification
    reasoning: str
    citation: str | None = Field(
        default=None, description="The rule, doc, or record that justifies this classification"
    )


class FieldMetadata(BaseModel):
    """Metadata for a single field in a table."""

    name: str
    label: str
    type: str
    mandatory: bool = False
    read_only: bool = False
    choices: list[str] = Field(default_factory=list)


class TableMetadata(BaseModel):
    """Metadata for a ServiceNow table."""

    name: str
    fields: dict[str, FieldMetadata] = Field(default_factory=dict)
    active_ui_policies: list[dict[str, Any]] = Field(default_factory=list)
    active_client_scripts: list[dict[str, Any]] = Field(default_factory=list)
    active_business_rules: list[dict[str, Any]] = Field(default_factory=list)


class CustomerKnowledgeModel:
    """Versioned snapshot of the instance's schema and rules.

    Provides deterministic rule resolution and anomaly classification based on
    discovered metadata.
    """

    def __init__(self, version: str = "1.0") -> None:
        self.version = version
        self.tables: dict[str, TableMetadata] = {}

    def add_table_metadata(self, table: TableMetadata) -> None:
        """Register or update metadata for a table."""
        self.tables[table.name] = table

    def get_table(self, name: str) -> TableMetadata | None:
        """Retrieve metadata for a table."""
        return self.tables.get(name)

    def classify_anomaly(
        self, anomaly_description: str, table_name: str, field_name: str | None = None
    ) -> ClassificationResult:
        """Classify an observed anomaly against known rules.

        Args:
            anomaly_description: Description of what went wrong (e.g. "Field became read-only")
            table_name: The table where this was observed
            field_name: The specific field, if applicable

        Returns:
            ClassificationResult explaining the anomaly.
        """
        table = self.get_table(table_name)
        if not table:
            return ClassificationResult(
                classification=AnomalyClassification.INCONCLUSIVE,
                reasoning=f"No metadata found for table '{table_name}'. Cannot determine if anomaly.",
            )

        # Example logic for demonstrating rule-based classification
        if field_name and field_name in table.fields:
            field = table.fields[field_name]

            if "mandatory" in anomaly_description.lower():
                if field.mandatory:
                    return ClassificationResult(
                        classification=AnomalyClassification.EXPECTED_CUSTOMIZATION,
                        reasoning=f"Field '{field_name}' is explicitly marked mandatory in dictionary.",  # noqa: E501
                        citation=f"sys_dictionary:{table_name}.{field_name}",
                    )
                else:
                    # Check UI policies
                    for policy in table.active_ui_policies:
                        if policy.get("makes_mandatory") == field_name:
                            return ClassificationResult(
                                classification=AnomalyClassification.EXPECTED_CUSTOMIZATION,
                                reasoning=f"Field '{field_name}' made mandatory by UI Policy '{policy.get('name')}'.",  # noqa: E501
                                citation=f"sys_ui_policy:{policy.get('sys_id')}",
                            )

                    return ClassificationResult(
                        classification=AnomalyClassification.APPLICATION_BUG,
                        reasoning=f"Field '{field_name}' is mandatory on screen but no dictionary or UI Policy dictates this.",  # noqa: E501
                    )

            if (
                "read-only" in anomaly_description.lower()
                or "read only" in anomaly_description.lower()
            ) and field.read_only:
                return ClassificationResult(
                    classification=AnomalyClassification.EXPECTED_CUSTOMIZATION,
                    reasoning=f"Field '{field_name}' is explicitly marked read_only in dictionary.",
                    citation=f"sys_dictionary:{table_name}.{field_name}",
                )

        # If we reach here, we don't have enough deterministic data, fallback to application bug assumption  # noqa: E501
        return ClassificationResult(
            classification=AnomalyClassification.INCONCLUSIVE,
            reasoning="Anomaly does not match any known discovered rules.",
        )

"""Tests for Domain Knowledge Model."""

from agent.domain.knowledge_model import (
    AnomalyClassification,
    CustomerKnowledgeModel,
    FieldMetadata,
    TableMetadata,
)


def test_classify_anomaly_mandatory_field_expected():
    model = CustomerKnowledgeModel()

    table = TableMetadata(name="incident")
    table.fields["short_description"] = FieldMetadata(
        name="short_description", label="Short description", type="string", mandatory=True
    )
    model.add_table_metadata(table)

    result = model.classify_anomaly(
        "Field short_description is mandatory", "incident", "short_description"
    )

    assert result.classification == AnomalyClassification.EXPECTED_CUSTOMIZATION
    assert "explicitly marked mandatory" in result.reasoning


def test_classify_anomaly_mandatory_field_bug():
    model = CustomerKnowledgeModel()

    table = TableMetadata(name="incident")
    table.fields["state"] = FieldMetadata(
        name="state", label="State", type="integer", mandatory=False
    )
    model.add_table_metadata(table)

    result = model.classify_anomaly("Field state is mandatory on screen", "incident", "state")

    assert result.classification == AnomalyClassification.APPLICATION_BUG
    assert "no dictionary or UI Policy dictates this" in result.reasoning


def test_classify_anomaly_unknown_table():
    model = CustomerKnowledgeModel()
    result = model.classify_anomaly("Something went wrong", "unknown_table")

    assert result.classification == AnomalyClassification.INCONCLUSIVE

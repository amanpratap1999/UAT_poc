from unittest.mock import AsyncMock, Mock

import pytest

from agent.cognition.investigation import InvestigationEngine
from agent.domain.knowledge_model import CustomerKnowledgeModel, FieldMetadata, TableMetadata


@pytest.fixture
def knowledge_model():
    km = Mock(spec=CustomerKnowledgeModel)

    table_meta = TableMetadata(
        name="change_request",
        fields={
            "justification": FieldMetadata(
                name="justification",
                type="string",
                mandatory=False,  # Customization: justification is optional
                label="Justification",
                read_only=False,
            ),
            "state": FieldMetadata(
                name="state", type="string", mandatory=True, label="State", read_only=False
            ),
        },
    )
    km.get_table.return_value = table_meta
    return km


@pytest.mark.asyncio
async def test_investigation_false_positive_customization(knowledge_model):
    engine = InvestigationEngine(knowledge_model=knowledge_model)

    # Simulate an expectation mismatch where we expected it to be mandatory, but it wasn't.
    result = await engine.investigate_mismatch(
        action=Mock(),
        expected="Field Justification should be mandatory",
        actual="Field Justification is optional and accepts empty submission",
        table_name="change_request",
    )

    assert not result.is_defect
    assert result.classification == "false_positive_customization"
    assert "CustomerKnowledgeModel" in result.reasoning


@pytest.mark.asyncio
async def test_investigation_verified_defect(knowledge_model):
    engine = InvestigationEngine(knowledge_model=knowledge_model)

    # State is mandatory in knowledge model, so if it's missing, it's a defect
    result = await engine.investigate_mismatch(
        action=Mock(),
        expected="Field State should be mandatory",
        actual="Field State is missing from form entirely",
        table_name="change_request",
    )

    assert result.is_defect
    assert result.classification == "verified_defect"


@pytest.mark.asyncio
async def test_investigation_learned_customization(knowledge_model):
    learning = AsyncMock()
    exp = Mock()
    exp.observation = "Custom UI Policy hides Priority field"
    exp.outcome = "expected_customization"
    learning.query_experiences.return_value = [exp]

    engine = InvestigationEngine(knowledge_model=knowledge_model, learning_service=learning)

    result = await engine.investigate_mismatch(
        action=Mock(),
        expected="Priority field should be visible",
        actual="Custom UI Policy hides Priority field",
        table_name="incident",
    )

    assert not result.is_defect
    assert result.classification == "learned_customization"

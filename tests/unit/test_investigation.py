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
async def test_investigation_verified_defect_requires_reproduction(knowledge_model):
    """QA-006: an unexplained mismatch is INCONCLUSIVE first; only a
    reproduced mismatch escalates to a verified defect."""
    engine = InvestigationEngine(knowledge_model=knowledge_model)

    # First occurrence: State is mandatory in knowledge model, so the mismatch
    # is a defect CANDIDATE — but not yet verified.
    first = await engine.investigate_mismatch(
        action=Mock(),
        expected="Field State should be mandatory",
        actual="Field State is missing from form entirely",
        table_name="change_request",
    )

    assert not first.is_defect
    assert first.classification == "inconclusive_unexplained_mismatch"

    # Reproduced from a clean baseline: now it can be verified.
    reproduced = await engine.investigate_mismatch(
        action=Mock(),
        expected="Field State should be mandatory",
        actual="Field State is missing from form entirely",
        table_name="change_request",
        reproduced=True,
    )

    assert reproduced.is_defect
    assert reproduced.classification == "verified_defect"


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

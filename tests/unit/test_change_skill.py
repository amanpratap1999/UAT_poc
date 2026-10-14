from agent.skills.change.domain.models import ChangeState, ChangeType
from agent.skills.change.domain.rules import ChangeBusinessRules


def test_change_lifecycle_transitions():
    assert ChangeBusinessRules.is_valid_transition(ChangeState.NEW, ChangeState.ASSESS) is True
    assert (
        ChangeBusinessRules.is_valid_transition(ChangeState.ASSESS, ChangeState.AUTHORIZE) is True
    )
    assert (
        ChangeBusinessRules.is_valid_transition(ChangeState.AUTHORIZE, ChangeState.SCHEDULED)
        is True
    )


def test_change_invalid_transitions():
    # Skipping states is invalid by default
    assert ChangeBusinessRules.is_valid_transition(ChangeState.NEW, ChangeState.IMPLEMENT) is False
    assert ChangeBusinessRules.is_valid_transition(ChangeState.ASSESS, ChangeState.CLOSED) is False


def test_change_mandatory_constraints():
    # New state has basic mandatory fields
    fields = ChangeBusinessRules.get_mandatory_fields_for_state(ChangeState.NEW, ChangeType.NORMAL)
    assert "short_description" in fields
    assert "assignment_group" in fields
    assert "justification" not in fields

    # Assess state requires more planning fields
    fields = ChangeBusinessRules.get_mandatory_fields_for_state(
        ChangeState.ASSESS, ChangeType.NORMAL
    )
    assert "justification" in fields
    assert "implementation_plan" in fields
    assert "test_plan" in fields

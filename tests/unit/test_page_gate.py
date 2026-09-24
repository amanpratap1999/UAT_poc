import pytest
from unittest.mock import Mock, AsyncMock

from agent.cognition.page_gate import PageGate, PageGateResult
from agent.domain.observation import PageObservation
from agent.domain.intent import StructuredIntent
from agent.core.types import PageType

@pytest.fixture
def page_gate():
    return PageGate()

def test_home_page_url_fails(page_gate):
    obs = PageObservation(
        url="https://instance.service-now.com/now/nav/ui/home",
        page_type=PageType.HOMEPAGE,
        record_number=None
    )
    intent = StructuredIntent(
        intent_type="GeneralValidation",
        goal="Verify incident INC0000007 is resolved",
        target_module="incident"
    )
    
    result = page_gate.check(obs, intent)
    assert not result.passed
    assert result.expected_record == "INC0000007"
    assert result.expected_table == "incident"
    assert result.observed_page_type == "homepage"

def test_incident_form_url_passes(page_gate):
    obs = PageObservation(
        url="https://instance.service-now.com/incident.do?sysparm_query=number=INC0000007",
        page_type=PageType.FORM,
        record_number="INC0000007"
    )
    intent = StructuredIntent(
        intent_type="GeneralValidation",
        goal="Verify incident INC0000007 is resolved",
        target_module="incident"
    )
    
    result = page_gate.check(obs, intent)
    assert result.passed
    assert result.expected_record == "INC0000007"

def test_mismatched_record_number_fails(page_gate):
    obs = PageObservation(
        url="https://instance.service-now.com/incident.do?sysparm_query=number=INC0000008",
        page_type=PageType.FORM,
        record_number="INC0000008"
    )
    intent = StructuredIntent(
        intent_type="GeneralValidation",
        goal="Verify incident INC0000007 is resolved",
        target_module="incident"
    )
    
    result = page_gate.check(obs, intent)
    assert not result.passed
    assert result.expected_record == "INC0000007"
    assert result.observed_record == "INC0000008"
    assert "does not match expected target" in result.reason

def test_dialog_page_type_fails(page_gate):
    obs = PageObservation(
        url="https://instance.service-now.com/some_dialog.do?number=INC0000007",
        page_type=PageType.DIALOG,
        record_number="INC0000007"
    )
    intent = StructuredIntent(
        intent_type="GeneralValidation",
        goal="Verify incident INC0000007",
        target_module="incident"
    )
    
    result = page_gate.check(obs, intent)
    assert not result.passed
    assert result.expected_record == "INC0000007"
    assert result.observed_page_type == "dialog"

def test_goal_text_parsing_extracts_correctly(page_gate):
    obs = PageObservation(
        url="https://instance.service-now.com/incident.do",
        page_type=PageType.FORM,
        record_number="CHG0000123"
    )
    intent = StructuredIntent(
        intent_type="GeneralValidation",
        goal="I want to approve CHG0000123 please",
        target_module="change"
    )
    
    result = page_gate.check(obs, intent)
    # The record number matches
    assert result.passed
    assert result.expected_record == "CHG0000123"
    assert result.expected_table == "change_request"

def test_goal_text_with_no_record_number_passes(page_gate):
    obs = PageObservation(
        url="https://instance.service-now.com/incident.do",
        page_type=PageType.FORM,
        record_number=None
    )
    intent = StructuredIntent(
        intent_type="GeneralValidation",
        goal="Create a new incident for network outage",
        target_module="incident"
    )
    
    result = page_gate.check(obs, intent)
    assert result.passed
    assert result.expected_record is None

"""Unit tests for Incident Observation (Deliverable 5)."""

from __future__ import annotations

from agent.domain.observation import PageObservation, PageType
from agent.skills.incident.domain.models import IncidentState
from agent.skills.incident.observation import IncidentObserver


def test_parse_incident_from_observation(sample_observation: PageObservation) -> None:
    """Test converting raw PageObservation to Incident domain object."""
    observer = IncidentObserver()
    inc = observer.parse_incident(sample_observation)

    assert inc.number == "INC0010001"
    assert inc.state == IncidentState.NEW
    assert inc.short_description == "Test incident"
    assert inc.caller == "Abel Tuter"


def test_parse_incident_unknown_state_stays_unknown() -> None:
    """QA-004: an unobserved state must stay UNKNOWN, never silently NEW."""
    observer = IncidentObserver()
    inc = observer.parse_incident(_observation(current_state=None))

    assert inc.state == IncidentState.UNKNOWN


def test_parse_incident_unknown_impact_urgency_stay_unknown() -> None:
    """QA-004: unobserved impact/urgency must stay UNKNOWN, never LOW."""
    observer = IncidentObserver()
    inc = observer.parse_incident(_observation())

    assert inc.impact.value == "unknown"
    assert inc.urgency.value == "unknown"
    assert inc.priority.value == "unknown"


def _observation(current_state: str | None = "New") -> PageObservation:
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc123",
        title="Incident | INC0010001",
        page_type=PageType.FORM,
        current_state=current_state,
        record_number="INC0010001",
        visible_fields=[],
        buttons=[],
        validation_messages=[],
    )

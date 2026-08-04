"""Unit tests for Incident Observation (Deliverable 5)."""

from __future__ import annotations

from agent.domain.observation import FieldInfo, PageObservation
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

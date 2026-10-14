"""Unit tests for Evidence Collection (Deliverable 9)."""

from __future__ import annotations

from agent.skills.incident.evidence import EvidenceCollector


def test_evidence_collection() -> None:
    """Test recording evidence items."""
    collector = EvidenceCollector()

    item = collector.record_evidence(
        step_description="Resolve Incident",
        expected_result="State is Resolved",
        observed_result="State is Resolved",
        passed=True,
        incident_number="INC0012345",
        reasoning_summary="Resolution notes filled",
        confidence_score=0.98,
    )

    assert item.evidence_id == "EV-001"
    assert item.passed is True
    assert item.confidence_score == 0.98
    assert len(collector.items) == 1

    summary = collector.get_summary_dict()
    assert summary[0]["evidence_id"] == "EV-001"

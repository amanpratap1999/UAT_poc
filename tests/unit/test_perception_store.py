from datetime import datetime, timedelta

import pytest

from agent.perception.models import BoundingBox, PerceptionCandidate, RecoveryMapping
from agent.perception.store import InMemoryRecoveryStore


@pytest.mark.asyncio
async def test_in_memory_recovery_store():
    store = InMemoryRecoveryStore()

    mapping = RecoveryMapping(
        original_target="Submit Button",
        recovered_candidate=PerceptionCandidate(
            source="vision",
            target_description="Submit Button",
            confidence=0.9,
            bounding_box=BoundingBox(x=10, y=10, width=100, height=30),
        ),
        confidence=0.9,
        page_fingerprint="/incident.do",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )

    await store.save_mapping(mapping)

    loaded = await store.get_mapping("Submit Button", "/incident.do")
    assert loaded is not None
    assert loaded.original_target == "Submit Button"

    await store.delete_mapping(mapping.mapping_id)
    loaded_deleted = await store.get_mapping("Submit Button", "/incident.do")
    assert loaded_deleted is None


@pytest.mark.asyncio
async def test_recovery_store_expiry():
    store = InMemoryRecoveryStore()

    mapping = RecoveryMapping(
        original_target="Expired Button",
        recovered_candidate=PerceptionCandidate(
            source="vision",
            target_description="Expired Button",
            confidence=0.9,
        ),
        confidence=0.9,
        page_fingerprint="/incident.do",
        expires_at=datetime.utcnow() - timedelta(days=1),  # already expired
    )

    await store.save_mapping(mapping)
    loaded = await store.get_mapping("Expired Button", "/incident.do")
    assert loaded is None

"""Unit tests for Knowledge Memory (Deliverable 8)."""

from __future__ import annotations

from pathlib import Path

from agent.memory.long_term import KnowledgeMemory


def test_knowledge_memory_recording_and_retrieval(tmp_path: Path) -> None:
    """Test recording and querying long-term instance learnings."""
    memory_file = tmp_path / "test_knowledge_memory.json"
    memory = KnowledgeMemory(storage_file=memory_file)

    learning = memory.record_learning(
        topic="incident.resolve",
        insight="Category and Resolution Code required before resolving",
        category="form_rules",
    )

    assert learning.topic == "incident.resolve"
    assert learning.times_observed == 1

    # Record again
    memory.record_learning(
        topic="incident.resolve",
        insight="Category and Resolution Code required before resolving",
        category="form_rules",
    )

    results = memory.query_learnings("resolve")
    assert len(results) == 1
    assert results[0].times_observed == 2

    summary = memory.get_prompt_summary("resolve")
    assert "Long-Term Instance Learnings:" in summary
    assert "Category and Resolution Code required" in summary

    # Verify persistence
    memory2 = KnowledgeMemory(storage_file=memory_file)
    assert len(memory2.query_learnings()) == 1

"""Long-Term Knowledge Memory for Deliverable 8.

Stores persistent instance-level learnings and rules across agent runs
(e.g., "This instance requires Category before Resolve", "Priority defaults to Medium").
These learnings influence future planning and decision-making.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agent.core.logging import get_logger

logger = get_logger(__name__)


class InstanceLearning(BaseModel):
    """A learned fact or rule about a ServiceNow instance."""

    learning_id: str
    category: str = Field(
        default="general", description="form_rules, field_defaults, workflow_constraints"
    )
    topic: str = Field(description="Specific topic or field name")
    insight: str = Field(description="The learned fact or rule")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    times_observed: int = 1
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeMemory:
    """Persistent store for cross-session instance learning."""

    def __init__(self, storage_file: Path = Path("reports/knowledge_memory.json")) -> None:
        self._storage_file = storage_file
        self._learnings: dict[str, InstanceLearning] = {}
        self._load()

    def record_learning(
        self, topic: str, insight: str, category: str = "general", confidence: float = 0.9
    ) -> InstanceLearning:
        """Record or update a learned rule about the ServiceNow instance.

        Args:
            topic: Field or feature topic (e.g., "incident.resolve").
            insight: The insight learned (e.g. "Category is required before resolving").
            category: Category string.
            confidence: Initial confidence.

        Returns:
            The InstanceLearning model.
        """
        learning_id = f"{category}:{topic}"
        if learning_id in self._learnings:
            existing = self._learnings[learning_id]
            existing.times_observed += 1
            existing.insight = insight
            existing.confidence = min(1.0, existing.confidence + 0.05)
            existing.last_updated = datetime.utcnow()
            learning = existing
        else:
            learning = InstanceLearning(
                learning_id=learning_id,
                category=category,
                topic=topic,
                insight=insight,
                confidence=confidence,
            )
            self._learnings[learning_id] = learning

        logger.info("recorded_instance_learning", topic=topic, insight=insight[:60])
        self.save()
        return learning

    def query_learnings(self, query: str = "") -> list[InstanceLearning]:
        """Query learnings matching a topic or keyword."""
        if not query:
            return list(self._learnings.values())
        q_lower = query.lower()
        return [
            learn
            for learn in self._learnings.values()
            if q_lower in learn.topic.lower()
            or q_lower in learn.insight.lower()
            or q_lower in learn.category.lower()
        ]

    def get_prompt_summary(self, query: str = "") -> str:
        """Produce a formatted summary of learnings for LLM context."""
        matching = self.query_learnings(query)
        if not matching:
            return ""

        lines = ["## Long-Term Instance Learnings:"]
        for learn in matching:
            lines.append(
                f"  - [{learn.topic}] {learn.insight} (Confidence: {learn.confidence:.2f})"
            )
        return "\n".join(lines)

    def _load(self) -> None:
        """Load stored learnings from disk."""
        if not self._storage_file.exists():
            return
        try:
            content = self._storage_file.read_text(encoding="utf-8")
            data = json.loads(content)
            for item in data:
                learning = InstanceLearning.model_validate(item)
                self._learnings[learning.learning_id] = learning
            logger.info("loaded_knowledge_memory", count=len(self._learnings))
        except Exception as e:
            logger.warning("failed_to_load_knowledge_memory", error=str(e))

    def save(self) -> None:
        """Save learnings to disk."""
        try:
            self._storage_file.parent.mkdir(parents=True, exist_ok=True)
            data = [learn.model_dump(mode="json") for learn in self._learnings.values()]
            self._storage_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("failed_to_save_knowledge_memory", error=str(e))

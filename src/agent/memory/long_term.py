"""Long-Term Knowledge Memory for Deliverable 8.

Stores persistent instance-level learnings and rules across agent runs
(e.g., "This instance requires Category before Resolve", "Priority defaults to Medium").
These learnings influence future planning and decision-making.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agent.core.config import REPO_ROOT
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
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeMemory:
    """Persistent store for cross-session instance learning."""

    def __init__(self, storage_file: Path = Path("reports/knowledge_memory.json")) -> None:
        # Audit issue I24 (P1): previously the path defaulted to a relative
        # Path that resolved against CWD. Concurrent API + worker processes
        # with different CWDs would write to two divergent files, silently
        # losing data. Now: resolve relative paths against REPO_ROOT so
        # all processes agree on one location.
        if not storage_file.is_absolute():
            storage_file = (REPO_ROOT / storage_file).resolve()
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
            existing.last_updated = datetime.now(UTC)
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
        """Save learnings to disk atomically.

        Audit issue I24 (P1): previously used non-atomic write_text directly
        to the storage file. A crash mid-write (or a concurrent writer)
        would leave a truncated JSON file that subsequent loads would
        silently fail to parse, losing all accumulated learnings. Now:
        1. Acquire an exclusive fcntl.flock on a sibling lockfile so
           concurrent writers (API + worker processes) serialize.
        2. Write to a NamedTemporaryFile in the same directory
           (so os.replace is atomic on the same filesystem).
        3. os.replace() to atomically swap the temp file into place.
        A crash at any point leaves either the old file (good) or the
        new file (good) — never a truncated intermediate state.
        """
        try:
            self._storage_file.parent.mkdir(parents=True, exist_ok=True)
            lockfile_path = self._storage_file.with_suffix(self._storage_file.suffix + ".lock")
            data = [learn.model_dump(mode="json") for learn in self._learnings.values()]
            payload = json.dumps(data, indent=2).encode("utf-8")

            # Open/create the lockfile (does NOT need to be the data file).
            # The flock is released when the file descriptor is closed
            # (automatically at end of `with` block).
            with open(lockfile_path, "w") as lockf:
                try:
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
                except (OSError, ValueError):
                    # flock not supported (Windows) — proceed without lock;
                    # the os.replace atomicity still protects against
                    # truncated reads, but concurrent writes may race.
                    pass

                # Write to a temp file in the SAME directory so os.replace
                # is atomic (same filesystem).
                fd, tmp_path = tempfile.mkstemp(
                    dir=self._storage_file.parent,
                    prefix=self._storage_file.name + ".",
                    suffix=".tmp",
                )
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(payload)
                    # os.replace is atomic on POSIX (same filesystem).
                    os.replace(tmp_path, self._storage_file)
                except Exception:
                    # Clean up the temp file on failure.
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
        except Exception as e:
            logger.warning("failed_to_save_knowledge_memory", error=str(e))

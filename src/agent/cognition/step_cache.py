"""Step to Action Cache (P0.3).

Caches standard resolutions to avoid hitting the LLM for identical semantic intents.
Persists across runs.
"""

import json
import sqlite3
from typing import Optional
from pathlib import Path

from agent.core.logging import get_logger
from agent.domain.actions import AgentAction

logger = get_logger(__name__)


class StepCache:
    """Caches decision engine resolutions."""

    def __init__(self, db_path: str = "step_cache.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS step_cache (
                    intent_hash TEXT PRIMARY KEY,
                    action_json TEXT NOT NULL
                )
                """
            )

    def _hash_intent(self, goal: str, intent_type: str, step_desc: str, expected: str) -> str:
        """Create a reproducible hash for the semantic intent."""
        import hashlib
        raw = f"{goal}::{intent_type}::{step_desc}::{expected}".lower()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_action(self, goal: str, intent_type: str, step_desc: str, expected: str) -> Optional[AgentAction]:
        """Retrieve a cached action if available."""
        h = self._hash_intent(goal, intent_type, step_desc, expected)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT action_json FROM step_cache WHERE intent_hash = ?", (h,))
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    action = AgentAction(**data)
                    logger.info("step_cache_hit", hash=h[:8], action_type=action.action_type)
                    return action
        except Exception as e:
            logger.warning("step_cache_read_error", error=str(e))
        return None

    def save_action(self, goal: str, intent_type: str, step_desc: str, expected: str, action: AgentAction) -> None:
        """Save a successful action to the cache."""
        h = self._hash_intent(goal, intent_type, step_desc, expected)
        try:
            # Need to handle enum serialization correctly
            data = action.model_dump(mode="json")
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO step_cache (intent_hash, action_json) VALUES (?, ?)",
                    (h, json.dumps(data))
                )
                logger.info("step_cache_saved", hash=h[:8], action_type=action.action_type)
        except Exception as e:
            logger.warning("step_cache_write_error", error=str(e))

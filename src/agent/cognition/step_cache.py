"""Step to Action Cache (P0.3).

Caches standard resolutions to avoid hitting the LLM for identical semantic intents.
Persists across runs via a settings-driven path (``AGENT_STEP_CACHE_PATH``),
shared between API and worker processes, safe for concurrent access (SQLite
WAL + busy timeout).

Also hosts ``step_parse_cache`` — a stable-hash cache of parsed human test
steps produced by the TestCaseImporter's semantic step parser.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from agent.core.logging import get_logger
from agent.domain.actions import AgentAction

logger = get_logger(__name__)

_CONNECT_TIMEOUT_SECONDS = 10.0


class StepCache:
    """Caches decision engine resolutions and parsed human test steps."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            from agent.core.config import resolve_step_cache_path

            db_path = str(resolve_step_cache_path())
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with write-ahead logging and busy tolerance."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.db_path,
            timeout=_CONNECT_TIMEOUT_SECONDS,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS step_cache (
                    intent_hash TEXT PRIMARY KEY,
                    action_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS step_parse_cache (
                    step_hash TEXT PRIMARY KEY,
                    parse_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _hash_intent(self, goal: str, intent_type: str, step_desc: str, expected: str) -> str:
        """Create a reproducible hash for the semantic intent."""
        raw = f"{goal}::{intent_type}::{step_desc}::{expected}".lower()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_step_text(step_text: str) -> str:
        """Stable hash for a raw human step's normalized text."""
        normalized = " ".join((step_text or "").split()).strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_action(self, goal: str, intent_type: str, step_desc: str, expected: str) -> Optional[AgentAction]:
        """Retrieve a cached action if available."""
        h = self._hash_intent(goal, intent_type, step_desc, expected)
        try:
            with self._connect() as conn:
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
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO step_cache (intent_hash, action_json) VALUES (?, ?)",
                    (h, json.dumps(data))
                )
                logger.info("step_cache_saved", hash=h[:8], action_type=action.action_type)
        except Exception as e:
            logger.warning("step_cache_write_error", error=str(e))

    # ------------------------------------------------------------------
    # Human step-parse cache (importer)
    # ------------------------------------------------------------------

    def get_parsed_step(self, step_text: str) -> Optional[dict[str, Any]]:
        """Return the cached parse for a unique human step, if present."""
        h = self.hash_step_text(step_text)
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "SELECT parse_json FROM step_parse_cache WHERE step_hash = ?", (h,)
                )
                row = cursor.fetchone()
                if row:
                    parsed = json.loads(row[0])
                    if isinstance(parsed, dict):
                        logger.info("step_parse_cache_hit", hash=h[:8])
                        return parsed
        except Exception as e:
            logger.warning("step_parse_cache_read_error", error=str(e))
        return None

    def save_parsed_step(self, step_text: str, parsed: dict[str, Any]) -> None:
        """Cache the semantic parse of a human step under a stable hash."""
        h = self.hash_step_text(step_text)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO step_parse_cache (step_hash, parse_json) VALUES (?, ?)",
                    (h, json.dumps(parsed)),
                )
                logger.info("step_parse_cache_saved", hash=h[:8])
        except Exception as e:
            logger.warning("step_parse_cache_write_error", error=str(e))

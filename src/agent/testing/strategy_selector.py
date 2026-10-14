"""Strategy Selector for Test Intelligence.

Loads test design strategies from JSON and applies composition rules
across field and workflow levels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.core.logging import get_logger
from agent.learning.service import LearningService

logger = get_logger(__name__)


class StrategySelector:
    """Selects and composes testing strategies based on UI elements and workflows."""

    def __init__(
        self, strategies_path: Path | None = None, learning_service: LearningService | None = None
    ) -> None:
        self._path = strategies_path or Path(__file__).parent / "strategies.json"
        self._learning = learning_service
        self._field_strategies: dict[str, list[str]] = {}
        self._workflow_strategies: dict[str, list[str]] = {}
        self._load_strategies()

    def _load_strategies(self) -> None:
        if not self._path.exists():
            logger.warning("strategies_file_not_found", path=str(self._path))
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._field_strategies = data.get("field_strategies", {})
            self._workflow_strategies = data.get("workflow_strategies", {})
        except Exception as e:
            logger.error("failed_to_load_strategies", error=str(e))

    async def select_strategies(
        self,
        fields: list[dict[str, Any]],
        workflow_type: str | None = None,
        target_module: str = "incident",
    ) -> list[str]:
        """Apply the composition rule for a given set of fields and workflow.

        Args:
            fields: List of field dicts, e.g., [{"type": "numeric", "name": "priority"}]
            workflow_type: The type of workflow, e.g., "approval" or "sla"
            target_module: The module context for the strategies

        Returns:
            A list of string explanations/citations for the strategies to apply.
        """
        # We will collect raw strategy info and then score it
        # List of (strategy_description, strategy_key, field_type, priority)
        candidates: list[tuple[str, str, str | None, float]] = []

        # 1. Field-level strategies compose additively
        for field in fields:
            f_type = field.get("type", "")
            f_name = field.get("name", "unknown")
            is_mandatory = field.get("mandatory", False)

            # Map types
            if f_type in ("integer", "decimal", "numeric"):
                strats = self._field_strategies.get("numeric", [])
                for s in strats:
                    candidates.append((f"[{s} for '{f_name}' (numeric field)]", s, "numeric", 1.0))
            elif f_type in ("date", "datetime"):
                strats = self._field_strategies.get("date", [])
                for s in strats:
                    candidates.append((f"[{s} for '{f_name}' (date field)]", s, "date", 1.0))
            elif f_type == "choice":
                strats = self._field_strategies.get("dropdown", [])
                for s in strats:
                    candidates.append((f"[{s} for '{f_name}' (dropdown field)]", s, "choice", 1.0))
            elif f_type == "boolean":
                strats = self._field_strategies.get("checkbox", [])
                for s in strats:
                    candidates.append((f"[{s} for '{f_name}' (checkbox field)]", s, "boolean", 1.0))
            elif f_type == "reference":
                strats = self._field_strategies.get("reference", [])
                for s in strats:
                    candidates.append(
                        (f"[{s} for '{f_name}' (reference field)]", s, "reference", 1.0)
                    )
            elif f_type == "string":
                strats = self._field_strategies.get("free_text", [])
                for s in strats:
                    candidates.append((f"[{s} for '{f_name}' (free text field)]", s, "string", 1.0))

            if is_mandatory:
                strats = self._field_strategies.get("mandatory", [])
                for s in strats:
                    candidates.append(
                        (f"[{s} for '{f_name}' (mandatory field)]", s, "mandatory", 1.0)
                    )

        # 2. Workflow-level strategies applied across the assembled form
        if workflow_type and workflow_type in self._workflow_strategies:
            w_strats = self._workflow_strategies[workflow_type]
            for s in w_strats:
                candidates.append((f"[{s} for workflow '{workflow_type}']", s, None, 1.0))

        # 3. Apply learning if available
        scored_candidates = []
        for desc, strat, ftype, prio in candidates:
            if self._learning:
                prio = await self._learning.get_strategy_priority(
                    module=target_module,
                    strategy=strat,
                    field_type=ftype,
                    workflow_type=workflow_type,
                )
            scored_candidates.append((prio, desc))

        # 4. Sort by priority (highest first) and deduplicate
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        seen = set()
        deduped = []
        for _prio, desc in scored_candidates:
            if desc not in seen:
                seen.add(desc)
                deduped.append(desc)

        return deduped

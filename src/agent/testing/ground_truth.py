"""Ground-truth evaluation scenarios and test suite definition.

Provides structures for evaluating agent testing performance (precision,
recall, false-pass rate, false-defect rate) against benchmark scenarios
with known (seeded) defects and clean controls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from agent.testing.generator import TestScenario


class GroundTruthScenario(TestScenario):
    """A test scenario with explicit ground-truth defect annotations."""

    is_clean: bool = True
    expected_defect_ids: list[str] = Field(default_factory=list)
    expected_defect_fields: list[str] = Field(default_factory=list)
    cleanup_steps: list[str] = Field(default_factory=list)
    story_context: dict[str, Any] = Field(default_factory=dict)
    workflow_type: str = "incident"


class GroundTruthSuite(BaseModel):
    """A collection of ground-truth scenarios for evaluation harness runs."""

    name: str = "ServiceNow UAT Ground Truth Benchmark"
    description: str = "Benchmark suite for evaluating defect detection quality."
    scenarios: list[GroundTruthScenario] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str | Path) -> GroundTruthSuite:
        """Load benchmark suite from JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def save_json(self, path: str | Path) -> None:
        """Save benchmark suite to JSON file."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

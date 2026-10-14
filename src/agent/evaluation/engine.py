"""Evaluation engine for tracking Phase 5 metrics and guardrails.

This module aggregates perception, testing intelligence, learning,
reliability, and efficiency metrics to prove the autonomous agent
outperforms the baseline.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PerceptionMetrics:
    total_actions: int = 0
    dom_successes: int = 0
    vision_fallbacks: int = 0
    recoveries_reused: int = 0
    recovery_failures: int = 0
    false_recoveries: int = 0


@dataclass
class TestingMetrics:
    total_scenarios: int = 0
    exploratory_scenarios: int = 0
    useful_findings: int = 0
    defect_yield: int = 0
    duplicate_findings: int = 0


@dataclass
class LearningMetrics:
    learning_reuse_count: int = 0
    strategy_improvements: int = 0


@dataclass
class ReliabilityMetrics:
    false_positives: int = 0
    false_negatives: int = 0
    uncertain_decisions: int = 0
    verification_failures: int = 0
    safety_blocks: int = 0


@dataclass
class EfficiencyMetrics:
    total_execution_ms: int = 0
    llm_calls: int = 0
    vision_calls: int = 0
    tokens_used: int = 0
    total_cost_usd: float = 0.0


@dataclass
class BenchmarkRun:
    run_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    perception: PerceptionMetrics = field(default_factory=PerceptionMetrics)
    testing: TestingMetrics = field(default_factory=TestingMetrics)
    learning: LearningMetrics = field(default_factory=LearningMetrics)
    reliability: ReliabilityMetrics = field(default_factory=ReliabilityMetrics)
    efficiency: EfficiencyMetrics = field(default_factory=EfficiencyMetrics)


class EvaluationEngine:
    """Tracks and aggregates evaluation metrics across runs."""

    def __init__(self) -> None:
        # In a full production setup, these would be written directly to a
        # Postgres time-series table. For this POC evaluation phase, we
        # store them in memory and expose them for reporting/benchmarking.
        self._runs: dict[str, BenchmarkRun] = {}
        self._current_run: BenchmarkRun | None = None

    def start_run(self, run_id: str) -> None:
        """Start a new benchmark run."""
        self._current_run = BenchmarkRun(run_id=run_id)
        self._runs[run_id] = self._current_run
        logger.info("evaluation_run_started", run_id=run_id)

    def get_current_run(self) -> BenchmarkRun:
        if not self._current_run:
            raise RuntimeError("No active benchmark run. Call start_run() first.")
        return self._current_run

    def record_perception(
        self,
        dom_success: bool = False,
        vision_fallback: bool = False,
        recovery_reused: bool = False,
        recovery_failure: bool = False,
        false_recovery: bool = False,
    ) -> None:
        """Record a perception-layer event."""
        if not self._current_run:
            return

        m = self._current_run.perception
        m.total_actions += 1
        if dom_success:
            m.dom_successes += 1
        if vision_fallback:
            m.vision_fallbacks += 1
            self.record_efficiency(vision_calls=1)
        if recovery_reused:
            m.recoveries_reused += 1
        if recovery_failure:
            m.recovery_failures += 1
        if false_recovery:
            m.false_recoveries += 1

    def record_testing(
        self,
        scenarios: int = 0,
        exploratory: int = 0,
        findings: int = 0,
        defects: int = 0,
        duplicates: int = 0,
    ) -> None:
        """Record test intelligence events."""
        if not self._current_run:
            return

        m = self._current_run.testing
        m.total_scenarios += scenarios
        m.exploratory_scenarios += exploratory
        m.useful_findings += findings
        m.defect_yield += defects
        m.duplicate_findings += duplicates

    def record_learning(
        self,
        reuse_count: int = 0,
        strategy_improved: bool = False,
    ) -> None:
        """Record operational learning events."""
        if not self._current_run:
            return

        m = self._current_run.learning
        m.learning_reuse_count += reuse_count
        if strategy_improved:
            m.strategy_improvements += 1

    def record_reliability(
        self,
        false_positive: bool = False,
        false_negative: bool = False,
        uncertain: bool = False,
        verification_failed: bool = False,
        safety_blocked: bool = False,
    ) -> None:
        """Record guardrail and reliability events."""
        if not self._current_run:
            return

        m = self._current_run.reliability
        if false_positive:
            m.false_positives += 1
        if false_negative:
            m.false_negatives += 1
        if uncertain:
            m.uncertain_decisions += 1
        if verification_failed:
            m.verification_failures += 1
        if safety_blocked:
            m.safety_blocks += 1

    def record_efficiency(
        self,
        execution_ms: int = 0,
        llm_calls: int = 0,
        vision_calls: int = 0,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        """Record execution efficiency metrics."""
        if not self._current_run:
            return

        m = self._current_run.efficiency
        m.total_execution_ms += execution_ms
        m.llm_calls += llm_calls
        m.vision_calls += vision_calls
        m.tokens_used += tokens
        m.total_cost_usd += cost

    def get_run_report(self, run_id: str) -> dict[str, Any]:
        """Generate a structured report for a specific run."""
        if run_id not in self._runs:
            raise ValueError(f"Run {run_id} not found.")

        run = self._runs[run_id]

        # Calculate derived metrics
        p = run.perception
        fallback_rate = (p.vision_fallbacks / p.total_actions) if p.total_actions > 0 else 0.0
        dom_success_rate = (p.dom_successes / p.total_actions) if p.total_actions > 0 else 0.0

        return {
            "run_id": run.run_id,
            "timestamp": run.timestamp.isoformat(),
            "perception": {
                "total_actions": p.total_actions,
                "dom_success_rate": round(dom_success_rate, 2),
                "vision_fallback_rate": round(fallback_rate, 2),
                "recoveries_reused": p.recoveries_reused,
                "false_recoveries": p.false_recoveries,
            },
            "testing": {
                "total_scenarios": run.testing.total_scenarios,
                "exploratory_ratio": round(
                    run.testing.exploratory_scenarios / run.testing.total_scenarios, 2
                )
                if run.testing.total_scenarios
                else 0.0,
                "defect_yield": run.testing.defect_yield,
            },
            "learning": {
                "reuses": run.learning.learning_reuse_count,
            },
            "reliability": {
                "false_positives": run.reliability.false_positives,
                "false_negatives": run.reliability.false_negatives,
                "safety_blocks": run.reliability.safety_blocks,
            },
            "efficiency": {
                "duration_sec": round(run.efficiency.total_execution_ms / 1000.0, 2),
                "llm_calls": run.efficiency.llm_calls,
                "vision_calls": run.efficiency.vision_calls,
                "cost_usd": round(run.efficiency.total_cost_usd, 4),
            },
        }

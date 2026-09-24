"""Incident UAT Benchmark Runner (INC-UAT-02 + INC-UAT-10).

Executes golden scenarios, measures recall/FP/misclassification/consistency,
and produces a structured benchmark report.

INC-UAT-02 (Blocker, D3): No demonstrated real/seeded Incident
defect-detection benchmark. This module provides the runner that
executes golden scenarios against the truth manifest and computes
TP/FN/FP/misclassification metrics.

INC-UAT-10 (Major, D9): No 3-run consistency benchmark. This module
runs each scenario ≥3 times and captures verdict/action/evidence
consistency across runs.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from agent.core.logging import get_logger
from agent.testing.golden_environment import GoldenTruthManifest, SeededDefect, get_default_manifest

logger = get_logger(__name__)


@dataclass
class ScenarioResult:
    """Result of executing a single golden scenario."""
    test_scenario: str  # e.g., "INC-G02"
    run_number: int  # 1, 2, or 3 (for 3-run consistency)
    verdict: str  # "PASS" | "FAIL" | "BLOCKED" | "CANNOT_VERIFY"
    detected_defect_id: str | None = None  # which seeded defect was detected
    detection_description: str = ""
    actions_taken: int = 0
    evidence_count: int = 0
    duration_seconds: float = 0.0
    human_intervention_steps: int = 0


@dataclass
class BenchmarkMetrics:
    """Aggregate metrics across all scenarios + all runs."""
    # Recall metrics
    true_positives: int = 0  # agent detected a real seeded defect
    false_negatives: int = 0  # agent missed a real seeded defect
    false_positives: int = 0  # agent reported a defect not in the manifest
    misclassifications: int = 0  # agent detected the defect but classified it wrong
    decoy_false_positives: int = 0  # agent reported a by-design decoy as a defect

    # Consistency metrics (INC-UAT-10)
    total_scenarios: int = 0
    consistent_scenarios: int = 0  # same verdict across all 3 runs
    inconsistent_scenarios: list[str] = field(default_factory=list)

    # Execution metrics
    total_runs: int = 0
    total_actions: int = 0
    total_human_intervention_steps: int = 0
    total_duration_seconds: float = 0.0

    # Per-scenario results
    scenario_results: list[ScenarioResult] = field(default_factory=list)

    @property
    def recall(self) -> float:
        """Recall = TP / (TP + FN)."""
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def precision(self) -> float:
        """Precision = TP / (TP + FP)."""
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def consistency_rate(self) -> float:
        """Fraction of scenarios that produced the same verdict across all runs."""
        return self.consistent_scenarios / self.total_scenarios if self.total_scenarios > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "true_positives": self.true_positives,
            "false_negatives": self.false_negatives,
            "false_positives": self.false_positives,
            "misclassifications": self.misclassifications,
            "decoy_false_positives": self.decoy_false_positives,
            "recall": round(self.recall, 3),
            "precision": round(self.precision, 3),
            "consistency_rate": round(self.consistency_rate, 3),
            "consistent_scenarios": self.consistent_scenarios,
            "total_scenarios": self.total_scenarios,
            "inconsistent_scenarios": self.inconsistent_scenarios,
            "total_runs": self.total_runs,
            "total_actions": self.total_actions,
            "total_human_intervention_steps": self.total_human_intervention_steps,
            "total_duration_seconds": round(self.total_duration_seconds, 1),
        }


class IncidentBenchmarkRunner:
    """Runs golden scenarios against the truth manifest and computes metrics.

    INC-UAT-02 + INC-UAT-10: executes each golden scenario 3 times,
    compares agent findings against the seeded truth manifest, and
    produces TP/FN/FP/misclassification/consistency metrics.

    Usage:
        runner = IncidentBenchmarkRunner()
        metrics = await runner.run_benchmark(
            scenario_executor=my_executor_fn,
            runs_per_scenario=3,
        )
        print(metrics.to_dict())
    """

    def __init__(self, manifest: GoldenTruthManifest | None = None) -> None:
        self._manifest = manifest or get_default_manifest()

    async def run_benchmark(
        self,
        scenario_executor: Any,
        runs_per_scenario: int = 3,
    ) -> BenchmarkMetrics:
        """Run all golden scenarios, compute metrics.

        Args:
            scenario_executor: async callable that takes (test_scenario: str, run_number: int)
                and returns a ScenarioResult. The executor is responsible for
                setting up the ServiceNow state, running the agent, and
                collecting the result.
            runs_per_scenario: how many times to run each scenario (default 3
                for INC-UAT-10 consistency measurement).

        Returns:
            BenchmarkMetrics with TP/FN/FP/consistency metrics.
        """
        metrics = BenchmarkMetrics()
        real_defect_ids = self._manifest.get_defect_ids()
        decoy_ids = self._manifest.get_decoy_ids()

        # Group results by scenario for consistency check
        scenario_verdicts: dict[str, list[str]] = {}

        for defect in self._manifest.defects:
            scenario = defect.test_scenario
            for run_num in range(1, runs_per_scenario + 1):
                logger.info(
                    "benchmark_run_start",
                    scenario=scenario,
                    run=run_num,
                    defect_id=defect.defect_id,
                    is_decoy=defect.is_decoy,
                )
                start_time = time.monotonic()
                try:
                    result: ScenarioResult = await scenario_executor(scenario, run_num)
                except Exception as e:
                    logger.error(
                        "benchmark_run_failed",
                        scenario=scenario,
                        run=run_num,
                        error=str(e),
                    )
                    result = ScenarioResult(
                        test_scenario=scenario,
                        run_number=run_num,
                        verdict="ERROR",
                        detection_description=f"Execution error: {e}",
                    )
                result.duration_seconds = time.monotonic() - start_time
                metrics.scenario_results.append(result)
                metrics.total_runs += 1
                metrics.total_actions += result.actions_taken
                metrics.total_human_intervention_steps += result.human_intervention_steps
                metrics.total_duration_seconds += result.duration_seconds

                # Track verdicts for consistency check
                scenario_verdicts.setdefault(scenario, []).append(result.verdict)

                # Score the result against the truth manifest
                detected = result.detected_defect_id
                if defect.is_decoy:
                    # Decoy: agent should NOT report a defect
                    if detected is not None:
                        metrics.decoy_false_positives += 1
                        logger.warning(
                            "decoy_false_positive",
                            scenario=scenario,
                            run=run_num,
                            decoy_id=defect.defect_id,
                            detected_id=detected,
                        )
                else:
                    # Real defect: agent should detect it
                    if detected == defect.defect_id:
                        metrics.true_positives += 1
                    elif detected is not None and detected in real_defect_ids:
                        # Detected a different real defect → misclassification
                        metrics.misclassifications += 1
                        logger.warning(
                            "misclassification",
                            scenario=scenario,
                            run=run_num,
                            expected=defect.defect_id,
                            detected=detected,
                        )
                    elif detected is not None and detected in decoy_ids:
                        # Reported a decoy as a defect → false positive
                        metrics.false_positives += 1
                    elif detected is None:
                        # Missed the real defect → false negative
                        metrics.false_negatives += 1
                    else:
                        # Reported something not in the manifest → false positive
                        metrics.false_positives += 1

        # Compute consistency (INC-UAT-10)
        unique_scenarios = set(scenario_verdicts.keys())
        metrics.total_scenarios = len(unique_scenarios)
        for scenario, verdicts in scenario_verdicts.items():
            if len(set(verdicts)) == 1:
                metrics.consistent_scenarios += 1
            else:
                metrics.inconsistent_scenarios.append(scenario)
                logger.warning(
                    "inconsistent_scenario",
                    scenario=scenario,
                    verdicts=verdicts,
                )

        logger.info(
            "benchmark_complete",
            recall=metrics.recall,
            precision=metrics.precision,
            consistency=metrics.consistency_rate,
            tp=metrics.true_positives,
            fn=metrics.false_negatives,
            fp=metrics.false_positives,
        )
        return metrics

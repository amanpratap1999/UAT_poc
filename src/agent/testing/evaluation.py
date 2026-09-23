from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from typing import Any
from pydantic import BaseModel, Field

from agent.core.config import get_settings
from agent.core.logging import get_logger
from agent.memory.session import SessionMemory
from agent.testing.generator import TestScenario
from agent.testing.ground_truth import GroundTruthScenario, GroundTruthSuite
from agent.testing.store import TestIntelligenceStore
from agent.main import AgentRunner

logger = get_logger(__name__)


class TestSuiteMetrics(BaseModel):
    """Aggregate evaluation metrics for autonomous testing execution."""

    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    defect_count: int = 0
    total_duration_seconds: float = 0.0
    mtbf_seconds: float = 0.0
    defect_density: float = 0.0  # defects per test scenario

    # Ground-truth evaluation metrics
    true_positives: int = 0  # real defect detected
    false_positives: int = 0  # defect reported but application is clean
    true_negatives: int = 0  # no defect expected, none reported
    false_negatives: int = 0  # defect expected, but missed (false pass)

    precision: float = 0.0  # TP / (TP + FP)
    recall: float = 0.0  # TP / (TP + FN)
    false_pass_rate: float = 0.0  # FN / (FN + TP)
    false_defect_rate: float = 0.0  # FP / (FP + TN)

    # Reproducibility metrics
    reproducibility_runs: int = 0
    reproducibility_agreement: float = 0.0  # Fraction of runs with identical verdicts

    # Defect breakdown
    defects_by_severity: dict[str, int] = Field(default_factory=dict)


class RunTestSuite:
    """Evaluation harness to autonomously generate and run test suites with ground truth."""

    def __init__(self, runner: AgentRunner, store: TestIntelligenceStore | None = None) -> None:
        self.runner = runner
        self.store = store
        self.metrics = TestSuiteMetrics()

    async def run_suite(self, requirement: str, max_scenarios: int = 5) -> TestSuiteMetrics:
        """Generate scenarios from requirement and run them."""
        logger.info("evaluation_harness_started", requirement=requirement, max_scenarios=max_scenarios)

        start_time = datetime.now(UTC)

        # 1. Autonomously generate test scenarios
        scenarios = await self.runner.generate_test_scenarios(
            requirement=requirement,
            fields=[],
            workflow_type="incident",
        )

        scenarios_to_run = scenarios[:max_scenarios]
        await self._execute_scenarios(scenarios_to_run, start_time)

        end_time = datetime.now(UTC)
        self.metrics.total_duration_seconds = (end_time - start_time).total_seconds()
        self._calculate_summary_metrics()

        logger.info("evaluation_harness_completed", metrics=self.metrics.model_dump())
        return self.metrics

    async def run_suite_with_ground_truth(
        self,
        suite: GroundTruthSuite,
        max_scenarios: int = 20,
    ) -> TestSuiteMetrics:
        """Execute a benchmark suite containing annotated ground-truth scenarios.

        Computes precision, recall, false-pass rate, and false-defect rate
        by comparing observed defects with known expected defects.
        """
        logger.info("ground_truth_evaluation_started", suite=suite.name, count=len(suite.scenarios))

        start_time = datetime.now(UTC)
        scenarios_to_run = suite.scenarios[:max_scenarios]

        last_failure_time = start_time
        failure_intervals: list[float] = []

        for idx, scenario in enumerate(scenarios_to_run):
            self.metrics.total_tests += 1
            logger.info("running_ground_truth_scenario", index=idx, description=scenario.description)

            tc_data = {
                "id": scenario.id or f"GT-{idx}",
                "description": scenario.description,
                "workflow_type": getattr(scenario, "workflow_type", "incident"),
                "steps": scenario.steps,
                "cleanup_steps": getattr(scenario, "cleanup_steps", []),
                "story_context": getattr(scenario, "story_context", {}),
            }
            self.runner._memory.test_case_data = tc_data

            report = await self.runner.run(scenario.description)
            has_defects = len(report.defects) > 0
            defect_expected = (
                not scenario.is_clean
                or len(scenario.expected_defect_ids) > 0
                or len(scenario.expected_defect_fields) > 0
            )

            # Evaluate confusion matrix
            if defect_expected:
                if has_defects:
                    self.metrics.true_positives += 1
                else:
                    self.metrics.false_negatives += 1  # False pass
            else:
                if has_defects:
                    self.metrics.false_positives += 1  # False defect
                else:
                    self.metrics.true_negatives += 1

            if report.status == "passed":
                self.metrics.passed_tests += 1
            else:
                self.metrics.failed_tests += 1
                now = datetime.now(UTC)
                failure_intervals.append((now - last_failure_time).total_seconds())
                last_failure_time = now

            self.metrics.defect_count += len(report.defects)
            for defect in report.defects:
                sev_key = getattr(defect.severity, "value", str(defect.severity)).lower()
                self.metrics.defects_by_severity[sev_key] = (
                    self.metrics.defects_by_severity.get(sev_key, 0) + 1
                )

            # Reset runner session memory for next scenario
            self.runner._memory = SessionMemory(
                observation_window=self.runner._settings.agent.observation_window
            )

        end_time = datetime.now(UTC)
        self.metrics.total_duration_seconds = (end_time - start_time).total_seconds()

        # MTBF
        if failure_intervals:
            self.metrics.mtbf_seconds = sum(failure_intervals) / len(failure_intervals)
        else:
            self.metrics.mtbf_seconds = self.metrics.total_duration_seconds

        # Defect Density
        if self.metrics.total_tests > 0:
            self.metrics.defect_density = self.metrics.defect_count / self.metrics.total_tests

        # Precision & Recall
        tp = self.metrics.true_positives
        fp = self.metrics.false_positives
        fn = self.metrics.false_negatives
        tn = self.metrics.true_negatives

        self.metrics.precision = (tp / (tp + fp)) if (tp + fp) > 0 else 1.0
        self.metrics.recall = (tp / (tp + fn)) if (tp + fn) > 0 else 1.0
        self.metrics.false_pass_rate = (fn / (fn + tp)) if (fn + tp) > 0 else 0.0
        self.metrics.false_defect_rate = (fp / (fp + tn)) if (fp + tn) > 0 else 0.0

        logger.info("ground_truth_evaluation_completed", metrics=self.metrics.model_dump())
        return self.metrics

    async def run_reproducibility_check(
        self,
        scenario: TestScenario,
        runs: int = 3,
    ) -> float:
        """Run the same scenario multiple times to measure verdict reproducibility."""
        if runs < 2:
            return 1.0

        logger.info("running_reproducibility_check", scenario=scenario.description, runs=runs)
        verdicts: list[tuple[str, int]] = []

        for r in range(runs):
            tc_data = {
                "id": f"{scenario.id}-rep-{r}",
                "description": scenario.description,
                "workflow_type": getattr(scenario, "workflow_type", "incident"),
                "steps": scenario.steps,
                "cleanup_steps": getattr(scenario, "cleanup_steps", []),
                "story_context": getattr(scenario, "story_context", {}),
            }
            self.runner._memory.test_case_data = tc_data

            report = await self.runner.run(scenario.description)
            verdicts.append((report.status, len(report.defects)))

            self.runner._memory = SessionMemory(
                observation_window=self.runner._settings.agent.observation_window
            )

        # Count modal verdict
        from collections import Counter
        counts = Counter(verdicts)
        most_common_verdict, most_common_count = counts.most_common(1)[0]
        agreement_ratio = most_common_count / runs

        self.metrics.reproducibility_runs = runs
        self.metrics.reproducibility_agreement = agreement_ratio
        logger.info(
            "reproducibility_check_completed",
            agreement=agreement_ratio,
            verdicts=verdicts,
        )
        return agreement_ratio

    async def _execute_scenarios(
        self,
        scenarios: list[TestScenario],
        start_time: datetime,
    ) -> None:
        last_failure_time = start_time
        failure_intervals: list[float] = []

        for idx, scenario in enumerate(scenarios):
            self.metrics.total_tests += 1
            logger.info("running_scenario", index=idx, description=scenario.description)

            tc_data = {
                "id": f"TC-{idx}",
                "description": scenario.description,
                "workflow_type": getattr(scenario, "workflow_type", "incident"),
                "steps": scenario.steps,
                "cleanup_steps": getattr(scenario, "cleanup_steps", []),
                "story_context": getattr(scenario, "story_context", {}),
            }
            self.runner._memory.test_case_data = tc_data

            report = await self.runner.run(scenario.description)

            if report.status == "passed":
                self.metrics.passed_tests += 1
            else:
                self.metrics.failed_tests += 1
                now = datetime.now(UTC)
                failure_intervals.append((now - last_failure_time).total_seconds())
                last_failure_time = now

            self.metrics.defect_count += len(report.defects)
            for defect in report.defects:
                sev_key = getattr(defect.severity, "value", str(defect.severity)).lower()
                self.metrics.defects_by_severity[sev_key] = (
                    self.metrics.defects_by_severity.get(sev_key, 0) + 1
                )

            self.runner._memory = SessionMemory(
                observation_window=self.runner._settings.agent.observation_window
            )

        if failure_intervals:
            self.metrics.mtbf_seconds = sum(failure_intervals) / len(failure_intervals)
        else:
            self.metrics.mtbf_seconds = (datetime.now(UTC) - start_time).total_seconds()

    def _calculate_summary_metrics(self) -> None:
        if self.metrics.total_tests > 0:
            self.metrics.defect_density = self.metrics.defect_count / self.metrics.total_tests

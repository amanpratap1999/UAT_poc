import pytest

from agent.testing.benchmark_runner import IncidentBenchmarkRunner, ScenarioResult
from agent.testing.golden_environment import GoldenTruthManifest, SeededDefect


def _manifest() -> GoldenTruthManifest:
    return GoldenTruthManifest(
        defects=[
            SeededDefect(
                defect_id="DEF-1",
                test_scenario="S1",
                defect_type="wrong_priority",
                description="seeded defect",
                expected_detection="detect it",
            )
        ]
    )


@pytest.mark.asyncio
async def test_benchmark_scores_three_consistent_true_positives():
    async def execute(scenario: str, run_number: int) -> ScenarioResult:
        return ScenarioResult(
            test_scenario=scenario,
            run_number=run_number,
            verdict="PASS",
            detected_defect_id="DEF-1",
        )

    metrics = await IncidentBenchmarkRunner(_manifest()).run_benchmark(execute, runs_per_scenario=3)

    assert metrics.total_runs == 3
    assert metrics.true_positives == 3
    assert metrics.false_negatives == 0
    assert metrics.false_positives == 0
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.consistency_rate == 1.0


@pytest.mark.asyncio
async def test_benchmark_counts_misclassification_in_precision_and_recall():
    async def execute(scenario: str, run_number: int) -> ScenarioResult:
        return ScenarioResult(
            test_scenario=scenario,
            run_number=run_number,
            verdict="PASS",
            detected_defect_id="OTHER-DEFECT",
        )

    metrics = await IncidentBenchmarkRunner(_manifest()).run_benchmark(execute, runs_per_scenario=3)

    assert metrics.misclassifications == 3
    assert metrics.false_negatives == 3
    assert metrics.false_positives == 3
    assert metrics.recall == 0.0
    assert metrics.precision == 0.0


@pytest.mark.asyncio
async def test_benchmark_does_not_hide_all_error_scenario_from_consistency_denominator():
    async def execute(scenario: str, run_number: int) -> ScenarioResult:
        return ScenarioResult(
            test_scenario=scenario,
            run_number=run_number,
            verdict="INFRA_ERROR",
            detection_description="setup unavailable",
        )

    metrics = await IncidentBenchmarkRunner(_manifest()).run_benchmark(execute, runs_per_scenario=3)

    assert metrics.total_scenarios == 1
    assert metrics.consistent_scenarios == 0
    assert metrics.inconsistent_scenarios == ["S1"]
    assert metrics.unscored_runs == 3

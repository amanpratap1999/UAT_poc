import pytest

from agent.evaluation.engine import EvaluationEngine


@pytest.fixture
def eval_engine() -> EvaluationEngine:
    return EvaluationEngine()


def test_benchmark_metrics_collection(eval_engine: EvaluationEngine) -> None:
    """Verify that the evaluation engine correctly aggregates Phase 5 metrics."""
    eval_engine.start_run("benchmark_run_01")

    # Simulate a run that performs 10 actions
    # 7 DOM success, 3 Visual Fallbacks
    for _ in range(7):
        eval_engine.record_perception(dom_success=True)

    for _ in range(3):
        eval_engine.record_perception(vision_fallback=True)

    # Simulate finding 2 real defects, 1 false positive, and generating 15 scenarios
    eval_engine.record_testing(scenarios=15, exploratory=3, findings=3, defects=2, duplicates=0)
    eval_engine.record_reliability(false_positive=True)

    # Simulate learning reuses
    eval_engine.record_learning(reuse_count=2, strategy_improved=True)

    report = eval_engine.get_run_report("benchmark_run_01")

    assert report["perception"]["total_actions"] == 10
    assert report["perception"]["dom_success_rate"] == 0.7
    assert report["perception"]["vision_fallback_rate"] == 0.3

    assert report["testing"]["total_scenarios"] == 15
    assert report["testing"]["defect_yield"] == 2

    assert report["reliability"]["false_positives"] == 1
    assert report["learning"]["reuses"] == 2


def test_golden_scenario_false_negative(eval_engine: EvaluationEngine) -> None:
    """Simulate a golden scenario where a bug was missed (false negative)."""
    eval_engine.start_run("golden_suite_incident_01")

    # Agent failed to flag an anomaly that was an actual bug
    eval_engine.record_reliability(false_negative=True)

    report = eval_engine.get_run_report("golden_suite_incident_01")
    assert report["reliability"]["false_negatives"] == 1

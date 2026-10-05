"""Human baseline comparison + run-to-run variance reporting (P2-11, D8/D10/D11).

Records a human tester's measured time + defect yield for each scenario as
the authoritative baseline, then compares the agent's measurements
against it. Also computes run-to-run variance so a reviewer can see
whether the agent produces the same verdict across repeated runs of the
same scenario.

Used by:
  • ``ReportingEngine`` (via ``report.environment["human_baseline_comparison"]``
    and ``report.environment["run_to_run_variance"]``)
  • ``IncidentBenchmarkRunner`` (consumes the variance report to surface
    consistency metrics in the benchmark summary)

The human baseline is loaded from a JSON file
(``reports/human_baseline.json`` by default) so QA managers can update it
without code changes. The file format is::

    {
      "scenarios": {
        "INC-G02": {
          "human_time_seconds": 180,
          "human_defects_found": 1,
          "human_notes": "Caught the priority mismatch on first inspection"
        },
        ...
      },
      "recorded_by": "qa_manager_name",
      "recorded_at": "2026-10-05T12:00:00Z"
    }

Run-to-run variance is computed from a list of agent run outcomes for the
same scenario. The output is a dict with:
  - ``n_runs``: number of runs considered
  - ``verdicts``: list of verdicts (in order)
  - ``mode_verdict``: the most common verdict
  - ``agreement_rate``: fraction of runs that match the mode
  - ``variance_label``: "consistent" / "mostly_consistent" / "inconsistent"
  - ``time_mean_seconds``, ``time_stddev_seconds``
  - ``defect_yield_mean``, ``defect_yield_stddev``
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class HumanBaselineRecord:
    """A human tester's measured outcome for one scenario."""
    scenario_id: str
    human_time_seconds: float
    human_defects_found: int
    human_notes: str = ""
    recorded_by: str = ""
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "human_time_seconds": self.human_time_seconds,
            "human_defects_found": self.human_defects_found,
            "human_notes": self.human_notes,
            "recorded_by": self.recorded_by,
            "recorded_at": self.recorded_at,
        }


@dataclass
class AgentRunMeasurement:
    """A single agent run's measurement for one scenario."""
    run_id: str
    scenario_id: str
    agent_time_seconds: float
    agent_defects_found: int
    verdict: str  # PASS | FAIL | BLOCKED | CANNOT_VERIFY | INFRA_ERROR | ERROR
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "agent_time_seconds": self.agent_time_seconds,
            "agent_defects_found": self.agent_defects_found,
            "verdict": self.verdict,
            "started_at": self.started_at,
        }


@dataclass
class RunVarianceReport:
    """Run-to-run variance summary for one scenario."""
    scenario_id: str
    n_runs: int
    verdicts: list[str] = field(default_factory=list)
    mode_verdict: str = ""
    agreement_rate: float = 0.0
    variance_label: str = "unknown"  # consistent | mostly_consistent | inconsistent | insufficient_data
    time_mean_seconds: float = 0.0
    time_stddev_seconds: float = 0.0
    defect_yield_mean: float = 0.0
    defect_yield_stddev: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "n_runs": self.n_runs,
            "verdicts": list(self.verdicts),
            "mode_verdict": self.mode_verdict,
            "agreement_rate": round(self.agreement_rate, 4),
            "variance_label": self.variance_label,
            "time_mean_seconds": round(self.time_mean_seconds, 2),
            "time_stddev_seconds": round(self.time_stddev_seconds, 2),
            "defect_yield_mean": round(self.defect_yield_mean, 4),
            "defect_yield_stddev": round(self.defect_yield_stddev, 4),
        }


@dataclass
class BaselineComparison:
    """Per-scenario agent-vs-human comparison."""
    scenario_id: str
    human_time_seconds: float
    agent_time_mean_seconds: float
    human_defects_found: int
    agent_defects_mean: float
    time_delta_seconds: float = 0.0
    time_ratio: float = 0.0  # agent_time / human_time
    defect_yield_delta: int = 0  # agent_mean - human

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "human_time_seconds": self.human_time_seconds,
            "agent_time_mean_seconds": round(self.agent_time_mean_seconds, 2),
            "human_defects_found": self.human_defects_found,
            "agent_defects_mean": round(self.agent_defects_mean, 4),
            "time_delta_seconds": round(self.time_delta_seconds, 2),
            "time_ratio": round(self.time_ratio, 4),
            "defect_yield_delta": self.defect_yield_delta,
        }


# ── Loaders ──

def load_human_baseline(path: str | Path = "reports/human_baseline.json") -> dict[str, HumanBaselineRecord]:
    """Load human baseline records from a JSON file.

    Returns an empty dict if the file does not exist — callers should
    treat this as "no human baseline available" rather than an error.
    """
    p = Path(path)
    if not p.is_file():
        logger.info("human_baseline_file_not_found", path=str(p))
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("human_baseline_load_failed", path=str(p), error=str(e))
        return {}
    out: dict[str, HumanBaselineRecord] = {}
    for scenario_id, entry in (data.get("scenarios") or {}).items():
        if not isinstance(entry, dict):
            continue
        out[str(scenario_id)] = HumanBaselineRecord(
            scenario_id=str(scenario_id),
            human_time_seconds=float(entry.get("human_time_seconds", 0.0) or 0.0),
            human_defects_found=int(entry.get("human_defects_found", 0) or 0),
            human_notes=str(entry.get("human_notes", "")),
            recorded_by=str(entry.get("recorded_by", "")),
            recorded_at=str(entry.get("recorded_at", "")),
        )
    return out


def save_human_baseline(
    records: dict[str, HumanBaselineRecord],
    path: str | Path = "reports/human_baseline.json",
    recorded_by: str = "",
) -> None:
    """Persist human baseline records to a JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenarios": {sid: r.to_dict() for sid, r in records.items()},
        "recorded_by": recorded_by,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("human_baseline_saved", path=str(p), scenario_count=len(records))


# ── Variance + comparison computation ──

def compute_run_variance(
    scenario_id: str,
    measurements: list[AgentRunMeasurement],
) -> RunVarianceReport:
    """Compute run-to-run variance for one scenario across N agent runs."""
    n = len(measurements)
    report = RunVarianceReport(scenario_id=scenario_id, n_runs=n)
    if n == 0:
        report.variance_label = "insufficient_data"
        return report

    verdicts = [m.verdict for m in measurements]
    report.verdicts = list(verdicts)
    # Mode verdict
    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    report.mode_verdict = max(counts, key=counts.get)
    report.agreement_rate = counts[report.mode_verdict] / n

    # Variance label
    if n < 3:
        report.variance_label = "insufficient_data"
    elif report.agreement_rate >= 1.0:
        report.variance_label = "consistent"
    elif report.agreement_rate >= 0.67:
        report.variance_label = "mostly_consistent"
    else:
        report.variance_label = "inconsistent"

    # Time statistics (only for non-error runs)
    times = [m.agent_time_seconds for m in measurements if m.agent_time_seconds > 0]
    if times:
        report.time_mean_seconds = statistics.fmean(times)
        report.time_stddev_seconds = statistics.pstdev(times) if len(times) > 1 else 0.0

    # Defect yield statistics
    yields = [float(m.agent_defects_found) for m in measurements]
    if yields:
        report.defect_yield_mean = statistics.fmean(yields)
        report.defect_yield_stddev = statistics.pstdev(yields) if len(yields) > 1 else 0.0

    return report


def compare_agent_to_human(
    scenario_id: str,
    baseline: HumanBaselineRecord,
    measurements: list[AgentRunMeasurement],
) -> BaselineComparison:
    """Compare agent measurements against a human baseline for one scenario."""
    times = [m.agent_time_seconds for m in measurements if m.agent_time_seconds > 0]
    yields = [float(m.agent_defects_found) for m in measurements]

    agent_time_mean = statistics.fmean(times) if times else 0.0
    agent_defects_mean = statistics.fmean(yields) if yields else 0.0

    comparison = BaselineComparison(
        scenario_id=scenario_id,
        human_time_seconds=baseline.human_time_seconds,
        agent_time_mean_seconds=agent_time_mean,
        human_defects_found=baseline.human_defects_found,
        agent_defects_mean=agent_defects_mean,
    )
    comparison.time_delta_seconds = agent_time_mean - baseline.human_time_seconds
    if baseline.human_time_seconds > 0:
        comparison.time_ratio = agent_time_mean / baseline.human_time_seconds
    comparison.defect_yield_delta = int(round(agent_defects_mean)) - baseline.human_defects_found
    return comparison


def build_baseline_comparison_section(
    measurements_by_scenario: dict[str, list[AgentRunMeasurement]],
    baseline_path: str | Path = "reports/human_baseline.json",
) -> dict[str, Any]:
    """Build a serializable comparison section for inclusion in a report.

    Returns a dict with:
      - ``human_baseline_loaded``: bool
      - ``scenarios``: dict[scenario_id, {comparison, variance}]
      - ``summary``: aggregate metrics
    """
    baselines = load_human_baseline(baseline_path)
    scenarios_out: dict[str, Any] = {}
    for scenario_id, measurements in measurements_by_scenario.items():
        variance = compute_run_variance(scenario_id, measurements)
        entry: dict[str, Any] = {"variance": variance.to_dict()}
        if scenario_id in baselines:
            comparison = compare_agent_to_human(scenario_id, baselines[scenario_id], measurements)
            entry["comparison"] = comparison.to_dict()
            entry["human_baseline"] = baselines[scenario_id].to_dict()
        else:
            entry["comparison"] = None
            entry["human_baseline"] = None
        scenarios_out[scenario_id] = entry

    return {
        "human_baseline_loaded": bool(baselines),
        "baseline_path": str(baseline_path),
        "scenarios": scenarios_out,
        "summary": {
            "scenario_count": len(scenarios_out),
            "scenarios_with_baseline": sum(
                1 for s in scenarios_out.values() if s.get("human_baseline")
            ),
            "consistent_scenarios": sum(
                1 for s in scenarios_out.values()
                if s["variance"].get("variance_label") == "consistent"
            ),
        },
    }
